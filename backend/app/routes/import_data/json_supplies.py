"""Supplies in a JSON backup: the pinned ones whole, and what each line item used (K12).

A pinned supply brings its whole ledger: its purchases, its standalone usages,
and a reference to each use on another vehicle's visit (`used_elsewhere`), so
its balance survives a restore in either order. A line item's usage names its
supply by its place in the file's `supplies`, or, for a shared supply or one
pinned elsewhere, by a name key looked up here. Quantities travel as decimal
text; a float keeps about 16 of the column's 25 digits.
"""

# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal, get_args

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import ColumnElement, and_, exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.address_book import AddressBookEntry
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.models.supply import Supply, SupplyPurchase, SupplyUsage
from app.models.user import User
from app.routes.import_data._common import (
    _blank_to_none,
    _check_bounds,
    _in_vocabulary,
    _json_bool,
    _json_decimal,
    _json_row_date,
    _json_row_datetime,
    _json_text,
    _RowError,
    _within_api_bounds,
)
from app.routes.import_data._families import (
    FamilyResult,
    as_object,
    file_index,
    nested_list,
    required_word,
    within_figure_bounds,
)
from app.routes.import_data._matching import _matches, _same_figure, _text_matches
from app.routes.import_data._service import usage_counts
from app.schemas._money import UNIT_COST_MAX, OptionalMoney
from app.schemas.supply import (
    SupplyAdjustmentCreate,
    SupplyPurchaseCreate,
    SupplyUnitType,
    SupplyUsageInput,
    SupplyVolumeUnit,
)
from app.services.auth import get_vehicle_or_403
from app.services.service_visit_service import ServiceVisitService

logger = logging.getLogger(__name__)

_UNIT_TYPES: tuple[str, ...] = get_args(SupplyUnitType)
_VOLUME_UNITS: tuple[str, ...] = get_args(SupplyVolumeUnit)
#: The unit-cost snapshot's column range. It's computed, so no schema bounds it.
_UNIT_COST_BOUNDS: list[Any] = Field(ge=0, le=UNIT_COST_MAX).metadata


@dataclass(frozen=True)
class SupplyKey:
    """How a supply is found by name: what tells two supplies apart here (K12)."""

    name: str
    part_number: str | None
    unit_type: str
    volume_unit: str | None


@dataclass(frozen=True)
class UsedElsewhere:
    """A use of a pinned supply on another vehicle's visit, named by that visit's line item."""

    vin: str
    used_on: date
    description: str
    quantity: Decimal
    unit_cost_snapshot: Decimal | None
    cost_snapshot: Decimal | None


@dataclass(frozen=True)
class UnnamedUse:
    """A use on a vehicle the exporter couldn't read: only how much, nothing to match."""

    quantity: Decimal


@dataclass(frozen=True)
class PinnedSupply:
    """One pinned supply, each purchase with its supplier's name, and its usages."""

    supply: Supply
    key: SupplyKey
    purchases: list[tuple[SupplyPurchase, str | None]]
    usages: list[SupplyUsage]
    used_elsewhere: list[UsedElsewhere | UnnamedUse]


@dataclass
class SupplyPlan:
    """Everything the file's pinned supplies write. The write adds its supplier warnings."""

    supplies: list[PinnedSupply]
    warnings: list[str] = field(default_factory=list[str])


@dataclass(frozen=True)
class LineItemUsage:
    """What a line item used: a supply in the file by index, or one found by key."""

    ref: int | SupplyKey
    quantity: Decimal
    unit_cost_snapshot: Decimal | None
    cost_snapshot: Decimal | None


def _supply_key(row: Mapping[str, Any], name_missing: str) -> SupplyKey:
    """A supply's key, held to SupplyCreate's vocabularies and its count rule (S4)."""
    name = _json_text(row, "name")
    if name is None:
        raise _RowError(name_missing)
    unit_type = required_word(row, "unit_type", _UNIT_TYPES)
    volume_unit = _in_vocabulary(
        _blank_to_none(row.get("volume_unit")), "volume_unit", _VOLUME_UNITS
    )
    if unit_type == "count" and volume_unit is not None:
        raise _RowError("A count supply cannot carry a volume unit")
    return SupplyKey(
        name=name,
        part_number=_json_text(row, "part_number"),
        unit_type=unit_type,
        volume_unit=volume_unit,
    )


def _snapshots(row: Mapping[str, Any]) -> tuple[Decimal | None, Decimal | None]:
    """A usage's unit cost and cost snapshots, each within its column."""
    unit_cost = _json_decimal(row, "unit_cost_snapshot")
    cost = _json_decimal(row, "cost_snapshot")
    if unit_cost is not None:
        _check_bounds("unit_cost_snapshot", unit_cost, _UNIT_COST_BOUNDS)
    within_figure_bounds(OptionalMoney, cost_snapshot=cost)
    return unit_cost, cost


def _required_quantity(row: Mapping[str, Any]) -> Decimal:
    quantity = _json_decimal(row, "quantity")
    if quantity is None:
        raise _RowError("quantity is missing")
    return quantity


def _purchase_from_json(row: Mapping[str, Any]) -> tuple[SupplyPurchase, str | None]:
    """One purchase as an unsaved row, with its supplier's name."""
    purchased_on = _json_row_date(row, "date")
    quantity = _required_quantity(row)
    total_cost = _json_decimal(row, "total_cost")
    _within_api_bounds(SupplyPurchaseCreate, quantity=quantity, total_cost=total_cost)
    purchase = SupplyPurchase(
        date=purchased_on,
        quantity=quantity,
        total_cost=total_cost,
        part_number=_json_text(row, "part_number"),
        notes=_json_text(row, "notes"),
    )
    return purchase, _json_text(row, "supplier_name")


def _standalone_usage_from_json(row: Mapping[str, Any]) -> SupplyUsage:
    """One standalone usage as an unsaved row. Its created_at is its ledger date."""
    quantity = _required_quantity(row)
    _within_api_bounds(SupplyAdjustmentCreate, quantity=quantity)
    unit_cost, cost = _snapshots(row)
    usage = SupplyUsage(quantity=quantity, unit_cost_snapshot=unit_cost, cost_snapshot=cost)
    created_at = _json_row_datetime(row, "created_at")
    # Missing keeps the column's default, the import's own now.
    if created_at is not None:
        usage.created_at = created_at
    return usage


def _used_elsewhere_from_json(row: Mapping[str, Any]) -> UsedElsewhere | UnnamedUse:
    """One use on another vehicle's visit, checked like a line item's usage."""
    # The exporter couldn't read that vehicle, so the file only says how much.
    if not any(k in row for k in ("vin", "date", "description")):
        quantity = _required_quantity(row)
        _within_api_bounds(SupplyUsageInput, quantity=quantity)
        return UnnamedUse(quantity)
    other_vin = _json_text(row, "vin")
    if other_vin is None:
        raise _RowError("vin is missing")
    used_on = _json_row_date(row, "date")
    description = _json_text(row, "description")
    if description is None:
        raise _RowError("description is missing")
    quantity = _required_quantity(row)
    _within_api_bounds(SupplyUsageInput, quantity=quantity)
    unit_cost, cost = _snapshots(row)
    return UsedElsewhere(other_vin, used_on, description, quantity, unit_cost, cost)


def _supply_from_json(vin: str, user_id: int | None, index: int, raw: Any) -> PinnedSupply:
    """One pinned supply with its ledger, every row checked."""
    try:
        row = as_object(raw)
        key = _supply_key(row, "name is missing")
        supply = Supply(
            vin=vin,
            name=key.name,
            part_number=key.part_number,
            barcode=_json_text(row, "barcode"),
            category=_json_text(row, "category"),
            unit_type=key.unit_type,
            volume_unit=key.volume_unit,
            is_active=_json_bool(row, "is_active", default=True),
            notes=_json_text(row, "notes"),
            created_by_user_id=user_id,
        )
        raw_purchases = nested_list(row, "purchases")
        raw_usages = nested_list(row, "usages")
        raw_used_elsewhere = nested_list(row, "used_elsewhere")
    except _RowError as e:
        raise _RowError(f"Supply {index}: {e.reason}") from e
    purchases: list[tuple[SupplyPurchase, str | None]] = []
    for j, raw_purchase in enumerate(raw_purchases):
        try:
            purchases.append(_purchase_from_json(as_object(raw_purchase)))
        except _RowError as e:
            raise _RowError(f"Supply {index}, purchase {j}: {e.reason}") from e
    usages: list[SupplyUsage] = []
    for j, raw_usage in enumerate(raw_usages):
        try:
            usages.append(_standalone_usage_from_json(as_object(raw_usage)))
        except _RowError as e:
            raise _RowError(f"Supply {index}, usage {j}: {e.reason}") from e
    used_elsewhere: list[UsedElsewhere | UnnamedUse] = []
    for j, raw_use in enumerate(raw_used_elsewhere):
        try:
            used_elsewhere.append(_used_elsewhere_from_json(as_object(raw_use)))
        except _RowError as e:
            raise _RowError(f"Supply {index}, used elsewhere {j}: {e.reason}") from e
    return PinnedSupply(
        supply=supply,
        key=key,
        purchases=purchases,
        usages=usages,
        used_elsewhere=used_elsewhere,
    )


def parse_supplies(vin: str, sections: Mapping[str, list[Any]], user_id: int | None) -> SupplyPlan:
    """The file's pinned supplies, every row checked, nothing touching the session."""
    return SupplyPlan(
        supplies=[
            _supply_from_json(vin, user_id, i, row) for i, row in enumerate(sections["supplies"])
        ]
    )


async def write_supplies(db: AsyncSession, plan: SupplyPlan, user: User | None) -> None:
    """Write the supplies, then their purchases and usages with each supply's new id.

    A supplier is the address book entry with that business name, lowest id
    first. One that isn't here leaves the purchase without one, with a warning:
    making an entry from an import would put it on the map (D-6). Each use on
    another vehicle's visit is then put back on that visit, or warned about.
    """
    db.add_all([pinned.supply for pinned in plan.supplies])
    await db.flush()
    suppliers: dict[str, int | None] = {}
    for i, pinned in enumerate(plan.supplies):
        for j, (purchase, supplier_name) in enumerate(pinned.purchases):
            purchase.supply_id = pinned.supply.id
            if supplier_name is None:
                continue
            if supplier_name not in suppliers:
                suppliers[supplier_name] = (
                    await db.execute(
                        select(AddressBookEntry.id)
                        .where(AddressBookEntry.business_name == supplier_name)
                        .order_by(AddressBookEntry.id)
                        .limit(1)
                    )
                ).scalar_one_or_none()
            purchase.supplier_id = suppliers[supplier_name]
            if purchase.supplier_id is None:
                plan.warnings.append(
                    f"Supply {i}, purchase {j}: its supplier isn't in this address book, "
                    "so it was saved without one"
                )
        for usage in pinned.usages:
            usage.supply_id = pinned.supply.id
        db.add_all([purchase for purchase, _name in pinned.purchases])
        db.add_all(pinned.usages)
    await db.flush()
    editable: dict[str, bool] = {}
    for pinned in plan.supplies:
        for use in pinned.used_elsewhere:
            if isinstance(use, UnnamedUse):
                plan.warnings.append(
                    f'{_plain(use.quantity)} of supply "{pinned.supply.name}" was used on '
                    "another vehicle's service, so it isn't counted"
                )
                continue
            if use.vin not in editable:
                editable[use.vin] = await _can_edit(db, use.vin, user)
            if editable[use.vin] and await _place_used_elsewhere(db, pinned, use):
                continue
            plan.warnings.append(
                f'{_plain(use.quantity)} of supply "{pinned.supply.name}" was used on '
                f"{use.vin}'s service on {use.used_on.isoformat()} and couldn't be "
                "matched here, so it isn't counted"
            )


def _plain(quantity: Decimal) -> str:
    """A quantity with no trailing zeros, the way a person would write it."""
    return format(quantity.normalize(), "f")


async def _can_edit(db: AsyncSession, vin: str, user: User | None) -> bool:
    """Whether `user` may write to that vehicle. A use never lands on one they can't."""
    try:
        await get_vehicle_or_403(vin, user, db, require_write=True)
    except HTTPException:
        return False
    return True


def _key_matches(key: SupplyKey) -> list[ColumnElement[bool]]:
    """A supply with the key's name, part number and units (K12)."""
    return [
        Supply.name == key.name,
        # A blank stored part number is none, as the file's reads.
        _text_matches(Supply.part_number, key.part_number),
        Supply.unit_type == key.unit_type,
        _matches(Supply.volume_unit, key.volume_unit),
    ]


async def _place_used_elsewhere(db: AsyncSession, pinned: PinnedSupply, use: UsedElsewhere) -> bool:
    """Put one use of `pinned` back on the other vehicle's visit; False when it isn't here.

    That vehicle restored first left the use on a shared supply with this key
    (the resolver adds a bare one), so it moves over. Deleting this vehicle took
    the use off that visit's item with it, so it's written back.
    """
    on_the_item = [
        ServiceVisit.vin == use.vin,
        ServiceVisit.date == use.used_on,
        ServiceLineItem.description == use.description,
    ]
    # Shared only: nothing else is pinned here yet, and a supply pinned to
    # another vehicle is a different supply (K12). A moved one leaves the pool.
    usage_id = (
        await db.execute(
            select(SupplyUsage.id)
            .join(Supply, SupplyUsage.supply_id == Supply.id)
            .join(ServiceLineItem, SupplyUsage.service_line_item_id == ServiceLineItem.id)
            .join(ServiceVisit, ServiceLineItem.visit_id == ServiceVisit.id)
            .where(
                *on_the_item,
                *_key_matches(pinned.key),
                Supply.vin.is_(None),
                _same_figure(SupplyUsage.quantity, use.quantity),
                _same_figure(SupplyUsage.unit_cost_snapshot, use.unit_cost_snapshot),
                _same_figure(SupplyUsage.cost_snapshot, use.cost_snapshot),
            )
            .order_by(SupplyUsage.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if usage_id is not None:
        # The shared one stays, empty or not. Nothing says it was only a
        # placeholder, and a real catalog item's details would go with it.
        # Same item and cost snapshot, so the visit's total doesn't move.
        await db.execute(
            update(SupplyUsage).where(SupplyUsage.id == usage_id).values(supply_id=pinned.supply.id)
        )
        return True

    has_this_supply = (
        exists()
        .where(
            SupplyUsage.service_line_item_id == ServiceLineItem.id,
            SupplyUsage.supply_id == Supply.id,
            *_key_matches(pinned.key),
        )
        .correlate(ServiceLineItem)
    )
    item = (
        await db.execute(
            select(ServiceLineItem.id, ServiceLineItem.visit_id)
            .join(ServiceVisit, ServiceLineItem.visit_id == ServiceVisit.id)
            .where(*on_the_item, ~has_this_supply)
            .order_by(ServiceLineItem.id)
            .limit(1)
        )
    ).first()
    if item is None:
        return False
    item_id, visit_id = item
    db.add(
        SupplyUsage(
            supply_id=pinned.supply.id,
            service_line_item_id=item_id,
            quantity=use.quantity,
            unit_cost_snapshot=use.unit_cost_snapshot,
            cost_snapshot=use.cost_snapshot,
        )
    )
    # That visit's cached total dropped this use if it was edited after the
    # cascade, and reports sum the cache.
    await ServiceVisitService(db).recompute_visit_total(visit_id)
    return True


def line_item_usages_from_json(
    position: int, item: Mapping[str, Any], file_supplies: list[Any]
) -> list[LineItemUsage]:
    """What one v9 line item used, each checked; a row error names the usage by its place."""
    try:
        raw_usages = nested_list(item, "supply_usages")
    except _RowError as e:
        raise _RowError(f"line item {position}: {e.reason}") from e
    usages: list[LineItemUsage] = []
    for k, raw in enumerate(raw_usages):
        try:
            row = as_object(raw)
            raw_supply = row.get("supply")
            if not isinstance(raw_supply, Mapping):
                raise _RowError("supply must be an object")
            supply = as_object(raw_supply)
            ref: int | SupplyKey
            if "index" in supply:
                index = file_index(
                    supply, "index", len(file_supplies), what="a supply in this file"
                )
                # A null index points nowhere either.
                if index is None:
                    raise _RowError("index must be the index of a supply in this file")
                ref = index
            else:
                ref = _supply_key(supply, "supply name is missing")
            quantity = _required_quantity(row)
            _within_api_bounds(SupplyUsageInput, quantity=quantity)
            unit_cost, cost = _snapshots(row)
        except _RowError as e:
            raise _RowError(f"line item {position}, supply usage {k}: {e.reason}") from e
        usages.append(LineItemUsage(ref, quantity, unit_cost, cost))
    return usages


def file_supply_key(file_supplies: list[Any], ref: int | SupplyKey) -> SupplyKey:
    """An index ref as its file row's key, read as the parse reads it; a key ref as itself."""
    if isinstance(ref, SupplyKey):
        return ref
    # A skipped family was never parsed, so its row can still be bad here.
    try:
        return _supply_key(as_object(file_supplies[ref]), "name is missing")
    except _RowError as e:
        raise _RowError(f"supply {ref}: {e.reason}") from e


def line_item_usage_counts(
    position: int, usages: list[LineItemUsage], file_supplies: list[Any]
) -> frozenset[tuple[tuple[Any, ...], int]]:
    """A file line item's `usage_counts`, each usage named by its supply's key."""
    entries: list[tuple[str, str | None, str, Decimal | None, Decimal | None, Decimal | None]] = []
    for k, usage in enumerate(usages):
        try:
            key = file_supply_key(file_supplies, usage.ref)
        except _RowError as e:
            raise _RowError(f"line item {position}, supply usage {k}: {e.reason}") from e
        entries.append(
            (
                key.name,
                key.part_number,
                key.unit_type,
                usage.quantity,
                usage.unit_cost_snapshot,
                usage.cost_snapshot,
            )
        )
    return usage_counts(entries)


#: Where a key is looked up: an index whose family was skipped, or a name key.
_Scope = Literal["pinned", "shared"]


class SupplyResolver:
    """Finds, or adds, the supply each line item usage names, one visit at a time.

    What a visit found or added sits in its own layer until its savepoint
    commits. A visit that rolls back takes its added supplies with it, so their
    cache entries and warnings go too (R1-H1): on SQLite the next supply added
    reuses the id, so a stale entry would point at the wrong one.
    """

    def __init__(
        self,
        vin: str,
        file_supplies: list[Any],
        user_id: int | None,
        family: FamilyResult[SupplyPlan],
    ) -> None:
        self._vin = vin
        self._file_supplies = file_supplies
        self._user_id = user_id
        self._family = family
        self._cache: dict[tuple[_Scope, SupplyKey], int] = {}
        self._visit_cache: dict[tuple[_Scope, SupplyKey], int] = {}
        self._visit_warnings: list[str] = []

    async def resolve(self, db: AsyncSession, ref: int | SupplyKey) -> int:
        """The id of the supply `ref` names; a row error when its family was refused."""
        if isinstance(ref, SupplyKey):
            return await self._find(db, "shared", ref)
        if self._family.outcome == "written" and self._family.plan is not None:
            return self._family.plan.supplies[ref].supply.id
        if self._family.outcome == "refused":
            # Nothing is added, so the fixed file's family still finds the vehicle without it (R1-H2).
            row = self._file_supplies[ref]
            name = as_object(row).get("name") if isinstance(row, Mapping) else None
            what = (
                f'the pinned supply "{name}"' if isinstance(name, str) else f"pinned supply {ref}"
            )
            raise _RowError(f"{what} was refused with its family")
        # Skipped: the vehicle has its own pinned supplies, so look the row up (D-5).
        # Never empty here: file_index already refused an index into no supplies.
        return await self._find(db, "pinned", file_supply_key(self._file_supplies, ref))

    async def stored_before(
        self, db: AsyncSession, usages: list[LineItemUsage], last_id: int
    ) -> list[LineItemUsage]:
        """The usages a visit stored before this import could hold.

        A key names a supply that isn't in this file. When none was stored with
        that key, no stored item can have used it. Usually its vehicle was
        deleted and took the use along. So it can't tell two visits apart, and restoring
        that vehicle puts the use back.
        """
        kept: list[LineItemUsage] = []
        for usage in usages:
            if isinstance(usage.ref, SupplyKey):
                found = await self._lookup(
                    db,
                    usage.ref,
                    and_(Supply.id <= last_id, or_(Supply.vin.is_(None), Supply.vin != self._vin)),
                )
                if found is None:
                    continue
            kept.append(usage)
        return kept

    def visit_done(self) -> list[str]:
        """Keep this visit's cache entries and hand back its warnings."""
        self._cache.update(self._visit_cache)
        self._visit_cache.clear()
        warnings, self._visit_warnings = self._visit_warnings, []
        return warnings

    def visit_failed(self) -> None:
        """Drop this visit's layer; its savepoint took the rows back."""
        self._visit_cache.clear()
        self._visit_warnings = []

    async def _find(self, db: AsyncSession, scope: _Scope, key: SupplyKey) -> int:
        cache_key = (scope, key)
        found = self._visit_cache.get(cache_key, self._cache.get(cache_key))
        if found is not None:
            return found
        if scope == "pinned":
            # This vehicle's own first, then the shared ones.
            places = [Supply.vin == self._vin, Supply.vin.is_(None)]
        else:
            # Shared first, then pinned to another vehicle (D-15). A key only ever
            # means "not pinned here", so this vehicle's own is never it (F-5).
            places = [Supply.vin.is_(None), and_(Supply.vin.isnot(None), Supply.vin != self._vin)]
        for place in places:
            found = await self._lookup(db, key, place)
            if found is not None:
                break
        if found is None:
            supply = Supply(
                name=key.name,
                part_number=key.part_number,
                unit_type=key.unit_type,
                volume_unit=key.volume_unit,
                vin=self._vin if scope == "pinned" else None,
                created_by_user_id=self._user_id,
            )
            db.add(supply)
            await db.flush()
            found = supply.id
            self._visit_warnings.append(
                f"Supply \"{key.name}\" wasn't in this household's supplies, "
                "so it was added with no stock"
            )
        self._visit_cache[cache_key] = found
        return found

    @staticmethod
    async def _lookup(db: AsyncSession, key: SupplyKey, place: ColumnElement[bool]) -> int | None:
        """The lowest-id supply in `place` with the key's name, part number and units (K12)."""
        return (
            await db.execute(
                select(Supply.id).where(*_key_matches(key), place).order_by(Supply.id).limit(1)
            )
        ).scalar_one_or_none()

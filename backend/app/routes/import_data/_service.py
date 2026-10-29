"""Service visits and line items: the CSV row, the visit key, the total and the write."""

# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date as date_type
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, selectinload

from app.models import (
    ServiceLineItem,
    ServiceVisit,
)
from app.models._types import ScaledNumeric
from app.models.supply import SupplyUsage
from app.models.vendor import Vendor
from app.routes.import_data._common import (
    _INSPECTION_RESULTS,
    _INSPECTION_SEVERITIES,
    _SERVICE_CATEGORIES,
    VALID_SERVICE_CATEGORIES,
    _blank_to_none,
    _ImportBoundError,
    _in_vocabulary,
    _json_decimal,
    _json_text,
    _RowError,
    _within_api_bounds,
    parse_date,
    parse_decimal,
)
from app.routes.import_data._matching import (
    _MONEY_STEP,
    _at_scale,
    _canonical_cell,
    _column_step,
    _money_matches,
    _text_matches,
)
from app.schemas._money import MONEY_MAX
from app.schemas.maintenance import validate_maintenance_type
from app.schemas.service_visit import (
    ServiceLineItemCreate,
    ServiceVisitCreate,
)
from app.utils.csv_units import (
    DISTANCE,
    CsvUnitContext,
)
from app.utils.maintenance_types import classify, resolve_type
from app.utils.money_fits import too_large


def _line_item_from_json(position: int, item: Any, count: int) -> tuple[dict[str, Any], int | None]:
    """One v9 line item's columns, and the index of the item that triggered it.

    The API's rules re-applied (R2); a row error names the item by `position`.
    """
    try:
        if not isinstance(item, Mapping):
            raise _RowError("must be an object")
        item = cast(Mapping[str, Any], item)
        description = _json_text(item, "description")
        if description is None:
            raise _RowError("description is missing")
        notes = _json_text(item, "notes")
        cost = _json_decimal(item, "cost")
        _within_api_bounds(ServiceLineItemCreate, cost=cost)
        category = _in_vocabulary(
            _blank_to_none(item.get("category")), "category", _SERVICE_CATEGORIES
        )
        inspection_result = _in_vocabulary(
            _blank_to_none(item.get("inspection_result")), "inspection_result", _INSPECTION_RESULTS
        )
        inspection_severity = _in_vocabulary(
            _blank_to_none(item.get("inspection_severity")),
            "inspection_severity",
            _INSPECTION_SEVERITIES,
        )
        try:
            maintenance_type = validate_maintenance_type(
                _blank_to_none(item.get("maintenance_type"))
            )
        except (ValueError, TypeError) as e:
            raise _RowError(
                "maintenance_type must be a lowercase snake_case code (2-50 chars)"
            ) from e
        link = item.get("triggered_by_inspection")
        if link is not None and (
            isinstance(link, bool)
            or not isinstance(link, int)
            or link not in range(count)
            or link == position
        ):
            raise _RowError(
                "triggered_by_inspection must be the index of another line item in this visit"
            )
    except _RowError as e:
        raise _RowError(f"line item {position}: {e.reason}") from e
    columns = {
        "description": description,
        "category": category,
        "maintenance_type": resolve_type(maintenance_type, description),
        "cost": cost,
        "notes": notes,
        "is_inspection": bool(item.get("is_inspection", False)),
        "inspection_result": inspection_result,
        "inspection_severity": inspection_severity,
    }
    return columns, link


@dataclass(frozen=True)
class _ServiceCsvRow:
    """One service CSV row: its visit's columns and its own line item."""

    row_num: int
    visit_number: str | None
    date: date_type
    category: str | None
    odometer_km: Decimal | None
    engine_hours: Decimal | None
    vendor_name: str | None
    tax_amount: Decimal | None
    shop_supplies: Decimal | None
    misc_fees: Decimal | None
    insurance_claim_number: str | None
    split_notes: bool  # the file has Item Notes and Visit Notes (v8)
    visit_notes: str | None
    item_notes: str | None  # a v<=7 file's one Notes cell lands here and in visit_notes
    description: str | None
    cost: Decimal | None
    has_item: bool

    @property
    def group(self) -> tuple[Any, ...]:
        """The visit the row belongs to: its number, else what one visit's rows share."""
        if self.visit_number:
            return ("visit", self.visit_number)
        # Hours too: an hours-only vehicle has no odometer to tell two same-day visits apart.
        return (
            "shared",
            self.date,
            self.odometer_km,
            self.engine_hours,
            self.vendor_name,
            self.category,
        )


#: What a v8 export repeats on each of a visit's rows, as (attribute, column).
_VISIT_FIELDS: tuple[tuple[str, str], ...] = (
    ("date", "Date"),
    ("category", "Category"),
    ("odometer_km", "Odometer"),
    ("engine_hours", "Engine Hours"),
    ("vendor_name", "Vendor"),
    ("tax_amount", "Tax"),
    ("shop_supplies", "Shop Supplies"),
    ("misc_fees", "Misc Fees"),
    ("insurance_claim_number", "Insurance Claim"),
    ("visit_notes", "Visit Notes"),
)


def _visit_disagreement(group: list[_ServiceCsvRow]) -> str | None:
    """Why one Visit's rows can't be one visit, or None when they agree.

    Only a v8 Visit-numbered group is checked; an older file's rows are grouped
    by these fields already. Values compare as parsed, so 1000 and 1000.00 agree.
    """
    first = group[0]
    if not first.visit_number:
        return None
    for attribute, column in _VISIT_FIELDS:
        expected = getattr(first, attribute)
        for row in group[1:]:
            if getattr(row, attribute) != expected:
                return (
                    f"Visit {first.visit_number}: rows {row.row_num} and {first.row_num} "
                    f"disagree on {column}"
                )
    return None


def _parse_service_row(
    row_num: int, row: Mapping[str, Any], units: CsvUnitContext
) -> _ServiceCsvRow:
    """One service CSV row read and held to the API's bounds; a row error says what's wrong."""

    def text(column: str) -> str | None:
        # The formula quote is already off (`_read_mygarage_csv`, T-21).
        return (row.get(column) or "").strip() or None

    date = parse_date(row.get("Date") or "")
    if not date:
        raise _RowError("Date is required")

    # Parse optional fields; accept both old and new header names
    raw_category = text("Category")
    service_type = text("Service Type")
    raw_description = text("Description")

    # "Category" maps to service_category if valid; "Service Type" is the description
    if raw_category and raw_category in VALID_SERVICE_CATEGORIES:
        category = raw_category
    elif service_type and service_type in VALID_SERVICE_CATEGORIES:
        category = service_type
    else:
        category = None

    # Distance arrives as a v6 token header (`Odometer (mi)`), as
    # `Odometer (km)`, or as legacy v2 `Mileage` in miles. `units`
    # already resolved which, from the file and nothing else.
    odometer_km = _canonical_cell(units, row, DISTANCE)
    # Engine-hours: hour-metered vehicles (ATVs, side-by-sides, equipment).
    # Dimensionless, no unit conversion (never present in legacy v2 CSVs).
    engine_hours = parse_decimal(row.get("Engine Hours") or "")
    cost = parse_decimal(row.get("Cost") or "")
    tax_amount = parse_decimal(row.get("Tax") or "")
    shop_supplies = parse_decimal(row.get("Shop Supplies") or "")
    misc_fees = parse_decimal(row.get("Misc Fees") or "")
    _within_api_bounds(
        ServiceVisitCreate,
        odometer_km=odometer_km,
        engine_hours=engine_hours,
        tax_amount=tax_amount,
        shop_supplies=shop_supplies,
        misc_fees=misc_fees,
    )
    _within_api_bounds(ServiceLineItemCreate, cost=cost)

    split_notes = "Item Notes" in row or "Visit Notes" in row
    if split_notes:
        item_notes = text("Item Notes")
        visit_notes = text("Visit Notes")
    else:
        item_notes = visit_notes = text("Notes")
    return _ServiceCsvRow(
        row_num=row_num,
        visit_number=(row.get("Visit") or "").strip() or None,
        date=date,
        category=category,
        odometer_km=odometer_km,
        engine_hours=engine_hours,
        vendor_name=text("Vendor") or text("Vendor Name"),
        tax_amount=tax_amount,
        shop_supplies=shop_supplies,
        misc_fees=misc_fees,
        insurance_claim_number=text("Insurance Claim"),
        split_notes=split_notes,
        visit_notes=visit_notes,
        item_notes=item_notes,
        # Use service_type or raw_category as description fallback
        description=raw_description or service_type or raw_category,
        cost=cost,
        # In v8 a row with no item cells is a visit with no line items, the
        # one row the export writes for one. An older file has no such row.
        has_item=(
            not split_notes
            or raw_description is not None
            or cost is not None
            or item_notes is not None
        ),
    )


async def _vendor_id_for(db: AsyncSession, name: str | None) -> int | None:
    """The vendor called `name`, made when there's none yet; None for no name."""
    if not name:
        return None
    vendor = (
        (await db.execute(select(Vendor).where(Vendor.name == name).limit(1))).scalars().first()
    )
    if vendor is None:
        vendor = Vendor(name=name)
        db.add(vendor)
        await db.flush()
    return vendor.id


def _visit_fee_key(row: _ServiceCsvRow, header: set[str]) -> list[ColumnElement[bool]]:
    """A visit's own amounts and claim number as match conditions; 0 and NULL alike.

    Without them two visits that differ only in tax match the same stored
    visit, and the first spends it (Codex R2). Each only when the sheet has
    its column (T-16, F-3): a hand-made sheet can carry Tax and no claim.
    """
    return [
        condition
        for column, condition in (
            ("Tax", _money_matches(ServiceVisit.tax_amount, row.tax_amount)),
            ("Shop Supplies", _money_matches(ServiceVisit.shop_supplies, row.shop_supplies)),
            ("Misc Fees", _money_matches(ServiceVisit.misc_fees, row.misc_fees)),
            (
                "Insurance Claim",
                _text_matches(ServiceVisit.insurance_claim_number, row.insurance_claim_number),
            ),
        )
        if column in header
    ]


#: What `_same_visit` reads off a stored visit, down to the supply each item used.
_VISIT_MATCH_LOADS = (
    selectinload(ServiceVisit.vendor),
    selectinload(ServiceVisit.line_items)
    .selectinload(ServiceLineItem.supply_usages)
    .selectinload(SupplyUsage.supply),
)


#: What else tells two line items apart: the work's category and how an
#: inspection came out (R1-H1). Notes are commentary, like a visit's, and
#: maintenance_type follows the classifier, which grows between versions.
_ITEM_KEY_FIELDS = ("category", "is_inspection", "inspection_result", "inspection_severity")


def _item_key_value(field: str, value: Any) -> Any:
    """One of `_ITEM_KEY_FIELDS` as the key reads it: a NULL flag is False, blank text None."""
    return bool(value) if field == "is_inspection" else _blank_to_none(value)


def _item_counts(keys: Iterable[tuple[Any, ...]]) -> Counter[tuple[Any, ...]]:
    """(description, cost, *rest) keys as counts, the cost at the cent, a missing one as 0 (v7 wrote $0 blank).

    The cent is the column's scale; a stored row reads back at it through the ORM (T-20).
    """
    # The description is trimmed on both sides: the CSV import strips its cell,
    # and the API keeps a stored one's spaces (Q-3).
    return Counter(
        (
            _blank_to_none(description.strip()) if isinstance(description, str) else description,
            _at_scale(cost, _MONEY_STEP) or Decimal(0),
            *rest,
        )
        for description, cost, *rest in keys
    )


#: Each usage figure's column step, so the file's figure and the stored one round alike (T-20).
_USAGE_STEPS = (
    _column_step(SupplyUsage.quantity),
    _column_step(SupplyUsage.unit_cost_snapshot),
    _column_step(SupplyUsage.cost_snapshot),
)


def usage_counts(
    entries: Iterable[tuple[str, str | None, str, Decimal | None, Decimal | None, Decimal | None]],
) -> frozenset[tuple[tuple[Any, ...], int]]:
    """One line item's usages as an order-free multiset: (name, part number, unit type, quantity, unit cost, cost).

    No volume unit: it's how the supply shows, and the quantity is canonical.
    A blank part number reads as none, as the file's does.
    """
    counts = Counter(
        (
            name,
            _blank_to_none(part_number),
            unit_type,
            *(_at_scale(value, step) for value, step in zip(figures, _USAGE_STEPS, strict=True)),
        )
        for name, part_number, unit_type, *figures in entries
    )
    return frozenset(counts.items())


def _row_item_counts(group: list[_ServiceCsvRow]) -> Counter[tuple[Any, ...]]:
    """The line items a group of rows writes, as `_write_service_csv_visit` names them."""
    return _item_counts(
        (row.description or row.category or "Service", row.cost) for row in group if row.has_item
    )


def _same_visit(
    visit: ServiceVisit,
    *,
    vendor_name: str | None,
    check_vendor: bool,
    items: Counter[tuple[Any, ...]] | None,
    item_fields: Sequence[str] = (),
    compare_usages: bool = False,
) -> bool:
    """Whether a stored visit (vendor and items loaded) is the file's visit (R5).

    `items` None means the file doesn't carry them, so they aren't compared.
    `item_fields` are the `_ITEM_KEY_FIELDS` the file's items carry, in order.
    With `compare_usages`, each file item's key ends in its `usage_counts`, so
    each stored item's key gets its own (R1-H4).
    """
    if check_vendor and (visit.vendor.name if visit.vendor else None) != vendor_name:
        return False
    if items is None:
        return True
    stored = _item_counts(
        (
            i.description,
            i.cost,
            *(_item_key_value(f, getattr(i, f)) for f in item_fields),
            *([_stored_usage_counts(i)] if compare_usages else []),
        )
        for i in visit.line_items
    )
    return stored == items


def _stored_usage_counts(item: ServiceLineItem) -> frozenset[tuple[tuple[Any, ...], int]]:
    """A stored line item's `usage_counts`, its usages and their supplies loaded."""
    return usage_counts(
        (
            u.supply.name,
            u.supply.part_number,
            u.supply.unit_type,
            u.quantity,
            u.unit_cost_snapshot,
            u.cost_snapshot,
        )
        for u in item.supply_usages
    )


def _as_stored(column: InstrumentedAttribute[Any], value: Decimal | None) -> Decimal | None:
    """`value` as `column` will store it: its own ScaledNumeric rounding."""
    column_type = column.type
    if not isinstance(column_type, ScaledNumeric):
        raise TypeError(f"{column} is not a ScaledNumeric column")
    return column_type.rounded(value)


def _visit_total(
    item_costs: Iterable[Decimal | None],
    tax_amount: Decimal | None,
    shop_supplies: Decimal | None,
    misc_fees: Decimal | None,
    usage_costs: Iterable[Decimal | None] = (),
) -> Decimal:
    """A written visit's total: its items' costs, the supplies they used and its fees.

    Each part is rounded the way its own column stores it before it's added, so
    the total is the sum of what's stored, not 20.01 for two items of 10.01 (Q-2).
    A row error past the largest amount the column holds, though each part fits.
    """
    parts = [
        *(_as_stored(ServiceLineItem.cost, cost) for cost in item_costs),
        # The app's own total counts each usage's cost snapshot too (K12).
        *(_as_stored(SupplyUsage.cost_snapshot, cost) for cost in usage_costs),
        _as_stored(ServiceVisit.tax_amount, tax_amount),
        _as_stored(ServiceVisit.shop_supplies, shop_supplies),
        _as_stored(ServiceVisit.misc_fees, misc_fees),
    ]
    total = sum((amount for amount in parts if amount is not None), Decimal(0))
    if total > MONEY_MAX:
        raise _ImportBoundError(too_large("The visit total"))
    return total


async def _write_service_csv_visit(
    db: AsyncSession, vin: str, group: list[_ServiceCsvRow]
) -> ServiceVisit:
    """One visit and its line items from a group of rows; the first row supplies the visit's columns."""
    first = group[0]
    if first.split_notes:
        visit_notes = first.visit_notes
        visit_took_notes = False
    else:
        # A v<=7 row's Notes were its item's, or the visit's when the item had
        # none, so the same Notes on every row are the visit's (T-13).
        visit_took_notes = len({row.item_notes for row in group}) == 1
        visit_notes = first.item_notes if visit_took_notes else None
    item_rows = [row for row in group if row.has_item]
    total_cost = _visit_total(
        (row.cost for row in item_rows), first.tax_amount, first.shop_supplies, first.misc_fees
    )

    visit = ServiceVisit(
        vin=vin,
        date=first.date,
        odometer_km=first.odometer_km,
        engine_hours=first.engine_hours,
        service_category=first.category or "Maintenance",
        vendor_id=await _vendor_id_for(db, first.vendor_name),
        tax_amount=first.tax_amount,
        shop_supplies=first.shop_supplies,
        misc_fees=first.misc_fees,
        insurance_claim_number=first.insurance_claim_number,
        notes=visit_notes,
        total_cost=total_cost,
    )
    db.add(visit)
    await db.flush()
    for row in item_rows:
        description = row.description or row.category or "Service"
        db.add(
            ServiceLineItem(
                visit_id=visit.id,
                description=description,
                maintenance_type=classify(description),
                # A blank cost stays blank (R2); it used to be written as 0.
                cost=row.cost,
                notes=None if visit_took_notes else row.item_notes,
            )
        )
    await db.flush()
    return visit

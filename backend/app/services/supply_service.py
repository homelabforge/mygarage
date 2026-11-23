"""Business logic for parts & supplies (light inventory).

On-hand and average cost are always derived from the ledgers — never stored —
so editing or deleting a purchase / job self-heals the balance.
"""

import logging
from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from sqlalchemy import ColumnElement, SQLColumnExpression, and_, case, func, or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.supply import Supply, SupplyPurchase, SupplyUsage
from app.models.user import User
from app.schemas._money import MONEY_MAX, UNIT_COST_MAX
from app.schemas.supply import (
    SupplyAdjustmentCreate,
    SupplyCreate,
    SupplyHistoryResponse,
    SupplyPurchaseCreate,
    SupplyResponse,
    SupplyUpdate,
    SupplyUsageResponse,
)
from app.utils.household_time import household_datetime, household_zone
from app.utils.logging_utils import sanitize_for_log
from app.utils.money_fits import ensure_fits

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")

#: What on-hand and running balances round to, in canonical units. Entries keep
#: 13 places, but 1.03 fl oz has 15 and loses a sliver to rounding, so 32 of
#: them leave -8E-13 L behind and a supply that's used up reads as short. This
#: hides that and nothing real: the smallest entry is 0.001.
BALANCE_GRAIN = Decimal("1E-9")


def ledger_balance(value: Decimal) -> Decimal:
    """A balance at BALANCE_GRAIN, with zero as plain 0.

    Rounding a tiny negative gives -0E-9, and that goes out on the wire as is.
    """
    balance = value.quantize(BALANCE_GRAIN, rounding=ROUND_HALF_UP)
    return balance if balance else _ZERO


def usage_cost_subject(supply_id: int) -> str:
    """How a usage's cost snapshot reads in a refusal, wherever it is computed."""
    return f"The cost of this much of supply {supply_id}"


def usage_cost(unit_cost: Decimal, quantity: Decimal) -> Decimal:
    """A usage's cost: unit cost times quantity, to the cent, half up. The one rounding
    every server path stores, and the one the editor's estimate mirrors."""
    return (unit_cost * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


#: A usage's (unit cost, estimated) as of its visit's date. Estimated means no
#: costed purchase on or before that day existed, so the unit is the all-time
#: average (#307).
AsOfPrice = tuple[Decimal, bool]

#: One costed purchase of a supply: (date, quantity, total_cost).
CostedPurchase = tuple[date, Decimal, Decimal]


def _average(purchases: Sequence[CostedPurchase]) -> Decimal | None:
    """Σ cost / Σ quantity at 4 places, half up, as every average rounds. None with no quantity."""
    cost = sum((c for _, _, c in purchases), _ZERO)
    qty = sum((q for _, q, _ in purchases), _ZERO)
    if qty <= 0:
        return None
    return (cost / qty).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def as_of_price(purchases: Sequence[CostedPurchase], as_of: date) -> AsOfPrice | None:
    """A usage's price as of `as_of` from its supply's costed purchases, or None.

    The average of the purchases dated on or before `as_of`; with none, the
    all-time average, estimated. None with no costed purchase at all. Migration
    163 prices stranded rows with the same rule, so the two must agree.
    """
    on_or_before = [p for p in purchases if p[0] <= as_of]
    unit = _average(on_or_before) if on_or_before else None
    if unit is not None:
        return unit, False
    fallback = _average(purchases)
    return None if fallback is None else (fallback, True)


def usage_price(
    unit_cost_snapshot: Decimal | None, quantity: Decimal, avg: Decimal | None
) -> tuple[Decimal, Decimal] | None:
    """The (unit cost, cost) an unpriced usage takes, or None if it can't be priced.

    Its own frozen unit cost wins over the average: an imported row can carry a
    unit cost and no cost, and that unit was the price at the time (#301). None
    when there's no unit to use, or the unit or cost won't fit its column.
    """
    unit = unit_cost_snapshot if unit_cost_snapshot is not None else avg
    if unit is None or unit > UNIT_COST_MAX:
        return None
    cost = usage_cost(unit, quantity)
    if cost > MONEY_MAX:
        return None
    return unit, cost


def price_unsettled_usage(usage: SupplyUsage, found: AsOfPrice | None) -> bool:
    """Price a usage whose price isn't settled yet; leave the rest alone. True if written.

    `found` is its supply's price as of the usage's visit (``as_of_price``).

    - No cost yet: priced at the first chance. A NULL cost means the cost was
      unknown when it was logged (no costed purchase yet), not that it was
      free: a free purchase prices at 0.00. Its own frozen unit wins if it has
      one and isn't flagged: an imported row can carry a unit and no cost, and
      that unit was the price at the time (#301). Otherwise `found`, flagged
      when it's the all-time fallback (#307).
    - An estimate settles only on a real as-of price, which clears the flag
      even when the amount doesn't move. A later receipt never moves it, and
      its own unit doesn't count: that unit IS the estimate.
    - Any other priced usage is frozen, whatever the averages do later.
    """
    if usage.cost_snapshot is None:
        own = None if usage.cost_estimated else usage.unit_cost_snapshot
        if own is not None:
            unit, estimated = own, False
        elif found is not None:
            unit, estimated = found
        else:
            return False
    elif usage.cost_estimated and found is not None and not found[1]:
        unit, estimated = found[0], False
    else:
        return False
    price = usage_price(None, usage.quantity, unit)
    if price is None:
        return False
    usage.unit_cost_snapshot, usage.cost_snapshot = price
    usage.cost_estimated = estimated
    return True


def unsettled_usage(visit_date: SQLColumnExpression[date]) -> ColumnElement[bool]:
    """Where-clause for the usages a pricer may write (D8), ``price_unsettled_usage``'s rule.

    A usage with no cost (always priced), or an estimate that a costed
    purchase dated on or before its visit can settle now. That second half is
    here, not just in the rule, so a purchase that can't settle an estimate
    doesn't walk and lock its vehicle. `visit_date` is the usage's visit's
    date, joined in by the caller; NULL (a standalone adjustment) settles nothing.
    """
    settles = (
        select(SupplyPurchase.id)
        .where(
            SupplyPurchase.supply_id == SupplyUsage.supply_id,
            SupplyPurchase.total_cost.isnot(None),
            SupplyPurchase.date <= visit_date,
        )
        .exists()
    )
    return or_(
        SupplyUsage.cost_snapshot.is_(None),
        and_(SupplyUsage.cost_estimated.is_(True), settles),
    )


class SupplyService:
    """Manage the supply catalog and its ledgers."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ---- balance math -------------------------------------------------------

    async def _compute_balances(
        self, supply_ids: list[int]
    ) -> dict[int, tuple[Decimal, Decimal | None]]:
        """Return {supply_id: (on_hand, avg_unit_cost)} for the given ids.

        on_hand = Σ purchase.quantity − Σ usage.quantity (all purchases count).
        avg_unit_cost = Σ total_cost / Σ quantity of cost-bearing purchases only;
        None if there are no cost-bearing purchases.
        """
        if not supply_ids:
            return {}

        p_rows = await self.db.execute(
            select(
                SupplyPurchase.supply_id,
                func.coalesce(func.sum(SupplyPurchase.quantity), _ZERO),
                func.coalesce(func.sum(SupplyPurchase.total_cost), _ZERO),
                func.coalesce(
                    func.sum(
                        case(
                            (SupplyPurchase.total_cost.isnot(None), SupplyPurchase.quantity),
                            else_=_ZERO,
                        )
                    ),
                    _ZERO,
                ),
            )
            .where(SupplyPurchase.supply_id.in_(supply_ids))
            .group_by(SupplyPurchase.supply_id)
        )
        purchases = {
            sid: (Decimal(str(qty)), Decimal(str(cost)), Decimal(str(costed_qty)))
            for sid, qty, cost, costed_qty in p_rows.all()
        }

        u_rows = await self.db.execute(
            select(SupplyUsage.supply_id, func.coalesce(func.sum(SupplyUsage.quantity), _ZERO))
            .where(SupplyUsage.supply_id.in_(supply_ids))
            .group_by(SupplyUsage.supply_id)
        )
        usages = {sid: Decimal(str(qty)) for sid, qty in u_rows.all()}

        result: dict[int, tuple[Decimal, Decimal | None]] = {}
        for sid in supply_ids:
            p_qty, p_cost, costed_qty = purchases.get(sid, (_ZERO, _ZERO, _ZERO))
            u_qty = usages.get(sid, _ZERO)
            on_hand = ledger_balance(p_qty - u_qty)
            avg = (
                (p_cost / costed_qty).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                if costed_qty > 0
                else None
            )
            result[sid] = (on_hand, avg)
        return result

    async def compute_avg_unit_cost(self, supply_id: int) -> Decimal | None:
        """Current weighted average unit cost for a single supply (for snapshots)."""
        return (await self._compute_balances([supply_id]))[supply_id][1]

    async def avg_unit_costs(self, supply_ids: list[int]) -> dict[int, Decimal | None]:
        """Current weighted average unit cost for each of several supplies."""
        balances = await self._compute_balances(supply_ids)
        return {sid: avg for sid, (_on_hand, avg) in balances.items()}

    async def _as_of_prices(
        self, supply_ids: Sequence[int], as_of: date
    ) -> dict[int, AsOfPrice | None]:
        """{supply_id: its price as of `as_of`} (see ``as_of_price``)."""
        if not supply_ids:
            return {}
        rows = await self.db.execute(
            select(
                SupplyPurchase.supply_id,
                SupplyPurchase.date,
                SupplyPurchase.quantity,
                SupplyPurchase.total_cost,
            ).where(SupplyPurchase.supply_id.in_(supply_ids))
        )
        costed: dict[int, list[CostedPurchase]] = {sid: [] for sid in supply_ids}
        for sid, day, quantity, total_cost in rows.all():
            if total_cost is not None:  # an uncosted purchase is in no average
                costed[sid].append((day, quantity, total_cost))
        return {sid: as_of_price(purchases, as_of) for sid, purchases in costed.items()}

    async def as_of_unit_cost(self, supply_id: int, as_of: date) -> AsOfPrice | None:
        """One supply's price as of a visit's date (for a new usage's snapshot)."""
        return (await self._as_of_prices([supply_id], as_of))[supply_id]

    async def as_of_unit_costs(
        self, supply_ids: Sequence[int], as_of: date
    ) -> dict[int, AsOfPrice | None]:
        """Several supplies' prices as of one visit's date (for the visit pricer)."""
        return await self._as_of_prices(supply_ids, as_of)

    def _to_supply_response(
        self, supply: Supply, on_hand: Decimal, avg: Decimal | None
    ) -> SupplyResponse:
        return SupplyResponse(
            id=supply.id,
            name=supply.name,
            part_number=supply.part_number,
            barcode=supply.barcode,
            category=supply.category,
            unit_type=supply.unit_type,
            volume_unit=supply.volume_unit,  # pyright: ignore[reportArgumentType]  # lenient vocab reads the stored str
            vin=supply.vin,
            notes=supply.notes,
            is_active=supply.is_active,
            on_hand=on_hand,
            avg_unit_cost=avg,
            is_negative=on_hand < 0,
            created_at=supply.created_at,
            updated_at=supply.updated_at,
        )

    # ---- catalog CRUD -------------------------------------------------------

    async def list_supplies(
        self,
        current_user: User | None,
        include_archived: bool = False,
        vin: str | None = None,
    ) -> tuple[list[SupplyResponse], int]:
        """List catalog supplies with computed balances.

        vin filter (for the consume-picker): returns shared supplies (vin IS NULL)
        plus supplies pinned to that vin.
        """
        try:
            stmt = select(Supply)
            if not include_archived:
                stmt = stmt.where(Supply.is_active.is_(True))
            if vin is not None:
                stmt = stmt.where((Supply.vin.is_(None)) | (Supply.vin == vin.upper().strip()))
            stmt = stmt.order_by(Supply.name)
            supplies = (await self.db.execute(stmt)).scalars().all()

            balances = await self._compute_balances([s.id for s in supplies])
            responses = [self._to_supply_response(s, *balances[s.id]) for s in supplies]
            return responses, len(responses)
        except OperationalError as e:
            logger.error("DB error listing supplies: %s", sanitize_for_log(e))
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def get_supply(self, supply_id: int) -> Supply:
        supply = (
            await self.db.execute(select(Supply).where(Supply.id == supply_id))
        ).scalar_one_or_none()
        if not supply:
            raise HTTPException(status_code=404, detail=f"Supply {supply_id} not found")
        return supply

    async def get_supply_with_balance(self, supply_id: int) -> SupplyResponse:
        """Get one supply as a response with its computed on-hand + avg cost."""
        supply = await self.get_supply(supply_id)
        on_hand, avg = (await self._compute_balances([supply_id]))[supply_id]
        return self._to_supply_response(supply, on_hand, avg)

    async def create_supply(self, data: SupplyCreate, current_user: User | None) -> SupplyResponse:
        supply = Supply(
            name=data.name,
            part_number=data.part_number,
            barcode=data.barcode,
            category=data.category,
            unit_type=data.unit_type,
            volume_unit=data.volume_unit,
            vin=data.vin.upper().strip() if data.vin else None,
            notes=data.notes,
            created_by_user_id=current_user.id if current_user else None,
        )
        self.db.add(supply)
        await self.db.commit()
        await self.db.refresh(supply)
        return self._to_supply_response(supply, _ZERO, None)

    async def update_supply(
        self, supply_id: int, data: SupplyUpdate, current_user: User | None
    ) -> SupplyResponse:
        supply = await self.get_supply(supply_id)
        payload = data.model_dump(exclude_unset=True)
        if "vin" in payload and payload["vin"]:
            payload["vin"] = payload["vin"].upper().strip()
        # unit_type isn't patchable, so only the stored supply knows if it's a count.
        # Checked before the setattr loop so a 422 leaves nothing dirty in the session.
        merged_unit = payload["volume_unit"] if "volume_unit" in payload else supply.volume_unit
        if supply.unit_type == "count" and merged_unit is not None:
            raise HTTPException(status_code=422, detail="A count supply cannot carry a volume unit")
        for field, value in payload.items():
            setattr(supply, field, value)
        await self.db.commit()
        await self.db.refresh(supply)
        on_hand, avg = (await self._compute_balances([supply.id]))[supply.id]
        return self._to_supply_response(supply, on_hand, avg)

    async def delete_supply(self, supply_id: int, current_user: User | None) -> bool:
        """Soft-archive if the supply has ledger history; hard-delete otherwise.

        Returns True if archived, False if hard-deleted.
        """
        supply = await self.get_supply(supply_id)
        has_purchases = (
            await self.db.execute(
                select(func.count())
                .select_from(SupplyPurchase)
                .where(SupplyPurchase.supply_id == supply_id)
            )
        ).scalar() or 0
        has_usages = (
            await self.db.execute(
                select(func.count())
                .select_from(SupplyUsage)
                .where(SupplyUsage.supply_id == supply_id)
            )
        ).scalar() or 0
        if has_purchases or has_usages:
            supply.is_active = False
            await self.db.commit()
            return True
        await self.db.delete(supply)
        await self.db.commit()
        return False

    # ---- purchases ----------------------------------------------------------

    async def add_purchase(
        self, supply_id: int, data: SupplyPurchaseCreate, current_user: User | None
    ) -> SupplyPurchase:
        await self.get_supply(supply_id)  # 404 if missing
        # Waits out any usage of it being logged (create_usage_snapshot), so the
        # pricing after this commit sees that usage, or the usage sees this cost.
        await self._lock_supply(supply_id, exclusive=True)
        purchase = SupplyPurchase(
            supply_id=supply_id,
            date=data.date,
            quantity=data.quantity,
            total_cost=data.total_cost,
            supplier_id=data.supplier_id,
            part_number=data.part_number,
            notes=data.notes,
        )
        self.db.add(purchase)
        await self.db.commit()
        await self.db.refresh(purchase)
        return purchase

    async def delete_purchase(
        self, supply_id: int, purchase_id: int, current_user: User | None
    ) -> None:
        purchase = (
            await self.db.execute(
                select(SupplyPurchase)
                .where(SupplyPurchase.id == purchase_id)
                .where(SupplyPurchase.supply_id == supply_id)
            )
        ).scalar_one_or_none()
        if not purchase:
            raise HTTPException(status_code=404, detail=f"Purchase {purchase_id} not found")
        old_files = await self._purge_receipt(purchase_id)  # rows now, files after commit (R1-H4)
        await self.db.delete(purchase)
        await self.db.commit()
        self._unlink_files(old_files)

    async def _purge_receipt(self, purchase_id: int) -> list[str]:
        """Delete receipt attachment ROWS for a purchase; return their file paths.

        Unlink the returned paths only AFTER the surrounding commit succeeds, so a
        rollback never loses a still-referenced file (R1-H4).
        """
        from app.models.attachment import Attachment

        rows = (
            (
                await self.db.execute(
                    select(Attachment)
                    .where(Attachment.record_type == "supply_purchase")
                    .where(Attachment.record_id == purchase_id)
                )
            )
            .scalars()
            .all()
        )
        paths = [a.file_path for a in rows]
        for a in rows:
            await self.db.delete(a)
        return paths

    @staticmethod
    def _unlink_files(paths: list[str]) -> None:
        from pathlib import Path

        for p in paths:
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not unlink receipt file %s", sanitize_for_log(p))

    # ---- usages / adjustments ----------------------------------------------

    async def create_usage_snapshot(
        self, supply_id: int, quantity: Decimal, as_of: date | None
    ) -> tuple[Decimal | None, Decimal | None, bool]:
        """Freeze (unit_cost, cost, estimated) for a new usage.

        `as_of` is the visit's date: the price as of that day, else the all-time
        average flagged as an estimate (#307). None, for a standalone adjustment,
        is the current average and never an estimate. No costed purchase at all
        is (None, None, False).

        Both are computed, so both are checked against their columns here: a
        huge purchase over a tiny quantity makes a unit cost no column holds.
        """
        # Held to commit: a purchase landing between this read and the usage's
        # commit would price before the usage exists and leave it unpriced (#301).
        await self._lock_supply(supply_id, exclusive=False)
        if as_of is None:
            unit, estimated = await self.compute_avg_unit_cost(supply_id), False
        else:
            found = await self.as_of_unit_cost(supply_id, as_of)
            unit, estimated = found if found is not None else (None, False)
        if unit is None:
            return None, None, False
        ensure_fits(unit, f"The unit cost of supply {supply_id}", UNIT_COST_MAX)
        cost = usage_cost(unit, quantity)
        ensure_fits(cost, usage_cost_subject(supply_id))
        return unit, cost, estimated

    async def _lock_supply(self, supply_id: int, *, exclusive: bool) -> None:
        """Lock the supply's row to commit: shared for a usage, exclusive for a purchase.

        PostgreSQL only; SQLite renders no FOR clause and already runs one
        writer at a time. Exclusive is FOR NO KEY UPDATE, so it doesn't block
        the key-share locks that inserting a purchase or usage row takes.
        """
        await self.db.execute(
            select(Supply.id)
            .where(Supply.id == supply_id)
            .with_for_update(read=not exclusive, key_share=exclusive)
        )

    async def add_adjustment(
        self, supply_id: int, data: SupplyAdjustmentCreate, current_user: User | None
    ) -> SupplyUsage:
        await self.get_supply(supply_id)
        # No visit, no date to price as of: today's average, never an estimate.
        unit_cost, cost, _estimated = await self.create_usage_snapshot(
            supply_id, data.quantity, as_of=None
        )
        usage = SupplyUsage(
            supply_id=supply_id,
            quantity=data.quantity,
            unit_cost_snapshot=unit_cost,
            cost_snapshot=cost,
            service_line_item_id=None,
        )
        self.db.add(usage)
        await self.db.commit()
        await self.db.refresh(usage)
        return usage

    async def delete_adjustment(
        self, supply_id: int, usage_id: int, current_user: User | None
    ) -> None:
        usage = (
            await self.db.execute(
                select(SupplyUsage)
                .where(SupplyUsage.id == usage_id)
                .where(SupplyUsage.supply_id == supply_id)
            )
        ).scalar_one_or_none()
        if not usage:
            raise HTTPException(status_code=404, detail=f"Adjustment {usage_id} not found")
        if usage.service_line_item_id is not None:
            raise HTTPException(
                status_code=400,
                detail="This usage is tied to a service line item; edit the visit instead",
            )
        await self.db.delete(usage)
        await self.db.commit()

    async def get_supply_for_use(self, supply_id: int, vin: str) -> Supply:
        """Validate a supply is usable on a given vehicle (shared or pinned to it, active)."""
        supply = await self.get_supply(supply_id)
        if not supply.is_active:
            raise HTTPException(status_code=400, detail=f"Supply {supply_id} is archived")
        if supply.vin is not None and supply.vin != vin.upper().strip():
            raise HTTPException(
                status_code=400,
                detail=f"Supply {supply_id} is pinned to a different vehicle",
            )
        return supply

    def to_usage_response(self, usage: SupplyUsage) -> SupplyUsageResponse:
        """Build a usage response.

        Callers MUST have ``usage.supply`` eager-loaded or resident in the session
        (this reads ``usage.supply.name``; ``supply_id`` is NOT NULL, so there is NO
        null short-circuit — an unloaded ``supply`` raises MissingGreenlet under async).
        For a JOB usage, callers MUST additionally eager-load
        ``usage.line_item → line_item.visit`` (same async rule). A standalone
        adjustment has ``service_line_item_id=None`` → ``line_item`` is None
        (SQLAlchemy short-circuits the null many-to-one, no query)."""
        line_item = usage.line_item
        visit = line_item.visit if (line_item is not None and line_item.visit) else None
        return SupplyUsageResponse(
            id=usage.id,
            supply_id=usage.supply_id,
            supply_name=usage.supply.name,
            unit_type=usage.supply.unit_type,
            volume_unit=usage.supply.volume_unit,  # pyright: ignore[reportArgumentType]  # lenient vocab reads the stored str
            quantity=usage.quantity,
            unit_cost_snapshot=usage.unit_cost_snapshot,
            cost_snapshot=usage.cost_snapshot,
            cost_estimated=usage.cost_estimated,
            service_line_item_id=usage.service_line_item_id,
            service_visit_id=visit.id if visit else None,
            service_visit_date=visit.date if visit else None,
            created_at=usage.created_at,
        )

    # ---- history ------------------------------------------------------------

    async def get_supply_history(
        self, supply_id: int, current_user: User | None
    ) -> SupplyHistoryResponse:
        from datetime import UTC, datetime, time

        from sqlalchemy.orm import selectinload

        from app.models.attachment import Attachment
        from app.models.service_line_item import ServiceLineItem
        from app.schemas.supply import SupplyLedgerEntry, SupplyReceiptSummary

        await self.get_supply(supply_id)
        purchases = (
            (
                await self.db.execute(
                    select(SupplyPurchase).where(SupplyPurchase.supply_id == supply_id)
                )
            )
            .scalars()
            .all()
        )
        usages = (
            (
                await self.db.execute(
                    select(SupplyUsage)
                    .where(SupplyUsage.supply_id == supply_id)
                    .options(
                        selectinload(SupplyUsage.line_item).selectinload(ServiceLineItem.visit)
                    )
                )
            )
            .scalars()
            .all()
        )

        # Batch-load receipt metadata for these purchases (R1-H4).
        receipts: dict[int, SupplyReceiptSummary] = {}
        if purchases:
            rows = (
                (
                    await self.db.execute(
                        select(Attachment)
                        .where(Attachment.record_type == "supply_purchase")
                        .where(Attachment.record_id.in_([p.id for p in purchases]))
                    )
                )
                .scalars()
                .all()
            )
            for a in rows:
                receipts[a.record_id] = SupplyReceiptSummary(id=a.id, file_type=a.file_type)

        # Effective ledger date (R1-H3): purchase.date; job usage → owning visit
        # date (real consumption date); standalone adjustment → created_at.
        # Dates are household days but created_at is naive UTC, so everything
        # goes on the household clock first or a near-midnight adjustment
        # lands on the wrong day.
        zone = household_zone()
        events: list[tuple[datetime, SupplyPurchase | SupplyUsage]] = []
        for p in purchases:
            events.append((datetime.combine(p.date, time.min, tzinfo=zone), p))
        for u in usages:
            visit = u.line_item.visit if (u.line_item and u.line_item.visit) else None
            eff = (
                datetime.combine(visit.date, time.min, tzinfo=zone)
                if visit
                else household_datetime(u.created_at)
            )
            events.append((eff, u))
        # Sort on the real instant, not the wall clock. In the fall-back hour a
        # later adjustment has an earlier wall clock and would jump the queue.
        # Same instant → purchases first, then by id.
        events.sort(
            key=lambda e: (
                e[0].astimezone(UTC),
                0 if isinstance(e[1], SupplyPurchase) else 1,
                e[1].id,
            )
        )

        entries: list[SupplyLedgerEntry] = []
        balance = _ZERO
        for at, obj in events:
            if isinstance(obj, SupplyPurchase):
                balance += obj.quantity
                entries.append(
                    SupplyLedgerEntry(
                        entry_type="purchase",
                        id=obj.id,
                        at=at,
                        ledger_date=at.date(),
                        quantity=obj.quantity,
                        running_balance=ledger_balance(balance),
                        cost=obj.total_cost,
                        supplier_id=obj.supplier_id,
                        receipt=receipts.get(obj.id),
                    )
                )
            else:
                balance -= obj.quantity
                visit = obj.line_item.visit if (obj.line_item and obj.line_item.visit) else None
                entries.append(
                    SupplyLedgerEntry(
                        entry_type="usage",
                        id=obj.id,
                        at=at,
                        ledger_date=at.date(),
                        quantity=-obj.quantity,
                        running_balance=ledger_balance(balance),
                        cost=obj.cost_snapshot,
                        cost_estimated=obj.cost_estimated,
                        service_line_item_id=obj.service_line_item_id,
                        service_visit_id=visit.id if visit else None,
                        service_visit_date=visit.date if visit else None,
                    )
                )
        on_hand, avg = (await self._compute_balances([supply_id]))[supply_id]
        return SupplyHistoryResponse(
            supply_id=supply_id, on_hand=on_hand, avg_unit_cost=avg, entries=entries
        )

    # ---- per-vehicle usage read ---------------------------------------------

    async def list_vehicle_supply_usages(self, vin: str, current_user: User | None):
        """Usages consumed on a vehicle (via its service line items). Read-gated."""
        from sqlalchemy.orm import selectinload

        from app.models.service_line_item import ServiceLineItem
        from app.models.service_visit import ServiceVisit
        from app.schemas.supply import VehicleSupplyUsagesResponse
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db)  # read gate (tripwire)
        rows = (
            (
                await self.db.execute(
                    select(SupplyUsage)
                    .join(ServiceLineItem, SupplyUsage.service_line_item_id == ServiceLineItem.id)
                    .join(ServiceVisit, ServiceLineItem.visit_id == ServiceVisit.id)
                    .where(ServiceVisit.vin == vin)
                    .options(
                        selectinload(SupplyUsage.supply),
                        # line_item -> visit needed for to_usage_response's owning-visit fields
                        # (async: unloaded -> MissingGreenlet). R1-H3.
                        selectinload(SupplyUsage.line_item).selectinload(ServiceLineItem.visit),
                    )
                    .order_by(ServiceVisit.date.desc(), SupplyUsage.id.desc())
                )
            )
            .scalars()
            .all()
        )
        usages = [self.to_usage_response(u) for u in rows]
        return VehicleSupplyUsagesResponse(usages=usages, total=len(usages))

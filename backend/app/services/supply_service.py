"""Business logic for parts & supplies (light inventory).

On-hand and average cost are always derived from the ledgers — never stored —
so editing or deleting a purchase / job self-heals the balance.
"""

import logging
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.supply import Supply, SupplyPurchase, SupplyUsage
from app.models.user import User
from app.schemas.supply import (
    SupplyAdjustmentCreate,
    SupplyCreate,
    SupplyHistoryResponse,
    SupplyPurchaseCreate,
    SupplyResponse,
    SupplyUpdate,
    SupplyUsageResponse,
)
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")


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
            on_hand = (p_qty - u_qty).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
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

    def _to_supply_response(
        self, supply: Supply, on_hand: Decimal, avg: Decimal | None
    ) -> SupplyResponse:
        return SupplyResponse(
            id=supply.id,
            name=supply.name,
            part_number=supply.part_number,
            category=supply.category,
            unit_type=supply.unit_type,
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
            category=data.category,
            unit_type=data.unit_type,
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
        self, supply_id: int, quantity: Decimal
    ) -> tuple[Decimal | None, Decimal | None]:
        """Freeze (unit_cost, cost) for a usage from the supply's current avg cost."""
        avg = await self.compute_avg_unit_cost(supply_id)
        if avg is None:
            return None, None
        cost = (avg * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return avg, cost

    async def add_adjustment(
        self, supply_id: int, data: SupplyAdjustmentCreate, current_user: User | None
    ) -> SupplyUsage:
        await self.get_supply(supply_id)
        unit_cost, cost = await self.create_usage_snapshot(supply_id, data.quantity)
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
            quantity=usage.quantity,
            unit_cost_snapshot=usage.unit_cost_snapshot,
            cost_snapshot=usage.cost_snapshot,
            service_line_item_id=usage.service_line_item_id,
            service_visit_id=visit.id if visit else None,
            service_visit_date=visit.date if visit else None,
            created_at=usage.created_at,
        )

    # ---- history ------------------------------------------------------------

    async def get_supply_history(
        self, supply_id: int, current_user: User | None
    ) -> SupplyHistoryResponse:
        from datetime import datetime, time

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
        events: list[tuple[datetime, str, object]] = []
        for p in purchases:
            events.append((datetime.combine(p.date, time.min), "purchase", p))
        for u in usages:
            visit = u.line_item.visit if (u.line_item and u.line_item.visit) else None
            eff = datetime.combine(visit.date, time.min) if visit else u.created_at
            events.append((eff, "usage", u))
        # Deterministic: same date → purchases first, then by id.
        events.sort(key=lambda e: (e[0], 0 if e[1] == "purchase" else 1, e[2].id))

        entries: list[SupplyLedgerEntry] = []
        balance = _ZERO
        for at, kind, obj in events:
            if kind == "purchase":
                balance += obj.quantity
                entries.append(
                    SupplyLedgerEntry(
                        entry_type="purchase",
                        id=obj.id,
                        at=at,
                        quantity=obj.quantity,
                        running_balance=balance.quantize(Decimal("0.001")),
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
                        quantity=-obj.quantity,
                        running_balance=balance.quantize(Decimal("0.001")),
                        cost=obj.cost_snapshot,
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

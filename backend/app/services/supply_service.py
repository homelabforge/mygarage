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
from app.schemas.supply import SupplyCreate, SupplyResponse, SupplyUpdate
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
            on_hand = (p_qty - u_qty).quantize(Decimal("0.001"))
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

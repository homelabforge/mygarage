"""Pricing a supply's usages after a purchase races cleanly (#301).

A costed purchase prices the usages its supply had before it had a cost, under
the vehicle write lock and with a re-read under it. Two purchases racing must
price each usage once, and a purchase racing a visit edit must leave the
visit's cached total equal to a fresh calculation. Each pricer is held after
it reads the averages and before it writes, so without the lock both price;
the count of pricings says so even when the stored figures would agree.

In `tests/integration/` so CI runs it on PostgreSQL as well as SQLite, with
real sessions per racer (the `client` fixture hands every request one session,
so it can't race). Modelled on `test_tire_concurrency.py`.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

import app.services.service_visit_service as service_visit_service
import app.services.supply_pricing as supply_pricing
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.models.supply import Supply, SupplyPurchase, SupplyUsage
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.service_visit import ServiceLineItemCreate, ServiceVisitUpdate
from app.schemas.supply import SupplyPurchaseCreate, SupplyUsageInput
from app.services.service_visit_service import ServiceVisitService
from app.services.supply_service import SupplyService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

QTY = Decimal("5")


@dataclass
class Seeded:
    user: User
    vin: str
    supply_id: int
    visit_id: int


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> AsyncIterator[Seeded]:
    """A committed admin, vehicle, bare supply and a visit using 5 of it, unpriced."""
    prefix = f"price{uuid.uuid4().hex[:6]}"
    user = User(
        username=f"{prefix}_user",
        email=f"{prefix}@example.com",
        hashed_password="x",
        is_active=True,
        is_admin=True,
    )
    db_session.add(user)
    await db_session.flush()
    vin = f"{prefix.upper()}00000000000"[:17]
    db_session.add(Vehicle(vin=vin, user_id=user.id, nickname=prefix, vehicle_type="Car"))
    supply = Supply(name=f"{prefix} oil", unit_type="volume")
    db_session.add(supply)
    await db_session.flush()
    visit = ServiceVisit(vin=vin, date=date(2026, 11, 17), total_cost=Decimal("10.00"))
    db_session.add(visit)
    await db_session.flush()
    item = ServiceLineItem(visit_id=visit.id, description="Oil change", cost=Decimal("10.00"))
    db_session.add(item)
    await db_session.flush()
    db_session.add(SupplyUsage(supply_id=supply.id, service_line_item_id=item.id, quantity=QTY))
    await db_session.commit()
    yield Seeded(user, vin, supply.id, visit.id)
    await db_session.rollback()
    await db_session.execute(delete(SupplyUsage).where(SupplyUsage.supply_id == supply.id))
    await db_session.execute(delete(SupplyPurchase).where(SupplyPurchase.supply_id == supply.id))
    await db_session.execute(delete(Supply).where(Supply.id == supply.id))
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
    await db_session.execute(delete(User).where(User.id == user.id))
    await db_session.commit()


def _hold_after_the_averages(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Hold each visit pricer between reading the averages and writing, and
    count the usages it prices. Under the lock the second pricer waits and then
    finds nothing; without it both read unpriced and both price. A hold, not a
    barrier: the loser blocks inside the driver on the lock and would never
    reach one."""
    original_avgs = SupplyService.avg_unit_costs

    async def slow(self: SupplyService, supply_ids: list[int]):
        result = await original_avgs(self, supply_ids)
        await asyncio.sleep(0.5)
        return result

    monkeypatch.setattr(SupplyService, "avg_unit_costs", slow)

    priced: list[int] = []
    original_price = service_visit_service.price_unpriced_usage

    def counted(usage: SupplyUsage, avg: Decimal | None) -> bool:
        did = original_price(usage, avg)
        if did:
            priced.append(usage.id)
        return did

    monkeypatch.setattr(service_visit_service, "price_unpriced_usage", counted)
    return priced


async def _purchase_and_price(
    sessionmaker: async_sessionmaker[AsyncSession], s: Seeded, cost: str
) -> None:
    async with sessionmaker() as db:
        user = await db.get(User, s.user.id)
        await SupplyService(db).add_purchase(
            s.supply_id,
            SupplyPurchaseCreate(
                date=date(2026, 11, 17), quantity=Decimal("10"), total_cost=Decimal(cost)
            ),
            user,
        )
        await supply_pricing.price_after_purchase(db, s.supply_id, s.user.id)


async def _state(sessionmaker: async_sessionmaker[AsyncSession], s: Seeded):
    async with sessionmaker() as db:
        usage = (
            await db.execute(select(SupplyUsage).where(SupplyUsage.supply_id == s.supply_id))
        ).scalar_one()
        visit = (
            await db.execute(
                select(ServiceVisit)
                .options(
                    selectinload(ServiceVisit.line_items).selectinload(
                        ServiceLineItem.supply_usages
                    )
                )
                .where(ServiceVisit.id == s.visit_id)
            )
        ).scalar_one()
        return (
            usage.unit_cost_snapshot,
            usage.cost_snapshot,
            visit.total_cost,
            visit.calculated_total_cost,
        )


def _cost(unit: Decimal) -> Decimal:
    return (unit * QTY).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def test_two_racing_purchases_price_the_usage_once(
    seeded: Seeded, test_sessionmaker, monkeypatch: pytest.MonkeyPatch
):
    priced = _hold_after_the_averages(monkeypatch)
    await asyncio.gather(
        _purchase_and_price(test_sessionmaker, seeded, "80.00"),  # 8.00 each
        _purchase_and_price(test_sessionmaker, seeded, "120.00"),  # 12.00 each
    )
    assert len(priced) == 1
    unit, cost, stored, fresh = await _state(test_sessionmaker, seeded)
    # Priced by whichever locked first, at the average it saw under the lock:
    # one purchase or both (10.00 over both).
    assert unit is not None and cost is not None
    assert unit in {Decimal("8.0000"), Decimal("12.0000"), Decimal("10.0000")}
    assert cost == _cost(unit)
    assert stored == fresh == Decimal("10.00") + cost

    # And frozen from here on.
    await _purchase_and_price(test_sessionmaker, seeded, "500.00")
    assert (await _state(test_sessionmaker, seeded))[:2] == (unit, cost)


async def test_a_purchase_racing_a_visit_edit_keeps_the_total_true(
    seeded: Seeded, test_sessionmaker, monkeypatch: pytest.MonkeyPatch
):
    priced = _hold_after_the_averages(monkeypatch)

    async def edit() -> None:
        await asyncio.sleep(0.1)  # inside the pricer's hold
        async with test_sessionmaker() as db:
            user = await db.get(User, seeded.user.id)
            await ServiceVisitService(db).update_service_visit(
                seeded.vin, seeded.visit_id, ServiceVisitUpdate(tax_amount=Decimal("3.00")), user
            )

    await asyncio.gather(_purchase_and_price(test_sessionmaker, seeded, "80.00"), edit())
    assert len(priced) == 1
    unit, cost, stored, fresh = await _state(test_sessionmaker, seeded)
    # The edit prices it too if it locks first; either way at 8.00 and once.
    assert (unit, cost) == (Decimal("8.0000"), Decimal("40.00"))
    assert stored == fresh == Decimal("53.00")


async def test_a_usage_logged_as_the_first_cost_lands_is_priced(
    seeded: Seeded, test_sessionmaker, monkeypatch: pytest.MonkeyPatch
):
    """The visit write logs the usage and its own pricing pass reads no average,
    then the purchase commits before the visit does. The pricing after the
    purchase must find the usage, or the visit must see the cost: otherwise
    it's left with none and no pricer comes back for it."""
    async with test_sessionmaker() as db:
        jug = Supply(name=f"{seeded.vin} coolant", unit_type="volume")
        db.add(jug)
        await db.commit()
        jug_id = jug.id

    # Held after the visit's pricing pass reads the averages, its usage in.
    original = SupplyService.avg_unit_costs

    async def slow(self: SupplyService, supply_ids: list[int]) -> dict[int, Decimal | None]:
        avgs = await original(self, supply_ids)
        await asyncio.sleep(0.5)
        return avgs

    monkeypatch.setattr(SupplyService, "avg_unit_costs", slow)

    async def top_up() -> None:
        async with test_sessionmaker() as db:
            user = await db.get(User, seeded.user.id)
            await ServiceVisitService(db).add_line_item(
                seeded.vin,
                seeded.visit_id,
                ServiceLineItemCreate(
                    description="Coolant top-up",
                    cost=Decimal("0"),
                    supplies_used=[SupplyUsageInput(supply_id=jug_id, quantity=Decimal("2"))],
                ),
                user,
            )

    async def buy() -> None:
        await asyncio.sleep(0.1)  # inside the visit's hold
        await _purchase_and_price(test_sessionmaker, replace(seeded, supply_id=jug_id), "20.00")

    try:
        await asyncio.gather(top_up(), buy())
        async with test_sessionmaker() as db:
            usage = (
                await db.execute(select(SupplyUsage).where(SupplyUsage.supply_id == jug_id))
            ).scalar_one()
            # 20.00 over 10: 2.00 a litre, 4.00 for 2.
            assert (usage.unit_cost_snapshot, usage.cost_snapshot) == (
                Decimal("2.0000"),
                Decimal("4.00"),
            )
        *_, stored, fresh = await _state(test_sessionmaker, seeded)
        assert stored == fresh == Decimal("14.00")
    finally:
        async with test_sessionmaker() as db:
            await db.execute(delete(SupplyUsage).where(SupplyUsage.supply_id == jug_id))
            await db.execute(delete(SupplyPurchase).where(SupplyPurchase.supply_id == jug_id))
            await db.execute(delete(Supply).where(Supply.id == jug_id))
            await db.commit()

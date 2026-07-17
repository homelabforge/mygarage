from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.models.supply import Supply
from app.models.vehicle import Vehicle
from app.schemas.supply import SupplyAdjustmentCreate, SupplyPurchaseCreate
from app.services.supply_service import SupplyService

pytestmark = [pytest.mark.asyncio, pytest.mark.supplies]


async def _supply(db, vin=None):
    s = Supply(name="Coolant", unit_type="volume", vin=vin)
    db.add(s)
    await db.flush()
    return s


async def _vehicle(db, vin, nickname="Test Car"):
    """Get-or-create a Vehicle by VIN. The test DB is shared (no per-test
    rollback) across the whole suite, so re-inserting a fixed VIN collides
    with other test files (e.g. the well-known `test_vehicle` fixture in
    tests/conftest.py). Mirror that fixture's get-or-create pattern here."""
    existing = (await db.execute(select(Vehicle).where(Vehicle.vin == vin))).scalar_one_or_none()
    if existing:
        return existing
    v = Vehicle(vin=vin, nickname=nickname, vehicle_type="Car")
    db.add(v)
    await db.flush()
    return v


async def test_purchase_then_adjustment_updates_on_hand(db_session):
    svc = SupplyService(db_session)
    s = await _supply(db_session)
    await svc.add_purchase(
        s.id,
        SupplyPurchaseCreate(date=date.today(), quantity=Decimal("4"), total_cost=Decimal("20.00")),
        None,
    )
    usage = await svc.add_adjustment(s.id, SupplyAdjustmentCreate(quantity=Decimal("1")), None)
    # snapshot frozen at avg cost 5.00/unit → 1 * 5 = 5.00
    assert usage.unit_cost_snapshot == Decimal("5.0000")
    assert usage.cost_snapshot == Decimal("5.00")
    on_hand, _ = (await svc._compute_balances([s.id]))[s.id]
    assert on_hand == Decimal("3.000")


async def test_history_running_balance_is_chronological(db_session):
    svc = SupplyService(db_session)
    s = await _supply(db_session)
    await svc.add_purchase(
        s.id, SupplyPurchaseCreate(date=date(2026, 1, 1), quantity=Decimal("10")), None
    )
    await svc.add_adjustment(s.id, SupplyAdjustmentCreate(quantity=Decimal("3")), None)
    hist = await svc.get_supply_history(s.id, None)
    assert [e.entry_type for e in hist.entries] == ["purchase", "usage"]
    assert hist.entries[0].running_balance == Decimal("10.000")
    assert hist.entries[1].running_balance == Decimal("7.000")
    assert hist.on_hand == Decimal("7.000")


async def test_get_supply_for_use_rejects_wrong_vehicle(db_session):
    svc = SupplyService(db_session)
    # Supply.vin is a real FK to vehicles.vin — the pinned vehicle must exist.
    vehicle = await _vehicle(db_session, "5YJ3E1EA1JF000001", nickname="Pinned Car")
    pinned = await _supply(db_session, vin=vehicle.vin)
    # Pinned to that VIN; requesting for another vehicle → 400.
    with pytest.raises(HTTPException) as ei:
        await svc.get_supply_for_use(pinned.id, "WAUZZZ8K9AA000001")
    assert ei.value.status_code == 400
    # Shared supply is usable anywhere.
    shared = await _supply(db_session)
    assert (await svc.get_supply_for_use(shared.id, "WAUZZZ8K9AA000001")).id == shared.id


async def test_delete_adjustment_rejects_job_usage(db_session):
    from app.models.supply import SupplyUsage

    svc = SupplyService(db_session)
    s = await _supply(db_session)
    # service_line_item_id is a real FK — build a genuine visit/line item chain
    # rather than an arbitrary literal id.
    vehicle = await _vehicle(db_session, "JT2BF22K1W0123456", nickname="Job Car")
    visit = ServiceVisit(vin=vehicle.vin, date=date.today())
    db_session.add(visit)
    await db_session.flush()
    line_item = ServiceLineItem(visit_id=visit.id, description="Coolant flush")
    db_session.add(line_item)
    await db_session.flush()
    job_usage = SupplyUsage(
        supply_id=s.id, quantity=Decimal("1"), service_line_item_id=line_item.id
    )
    db_session.add(job_usage)
    await db_session.flush()
    with pytest.raises(HTTPException) as ei:
        await svc.delete_adjustment(s.id, job_usage.id, None)
    assert ei.value.status_code == 400  # only standalone adjustments deletable here

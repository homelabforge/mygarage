from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.supply import Supply, SupplyPurchase, SupplyUsage
from app.schemas.supply import SupplyCreate, SupplyUpdate
from app.services.supply_service import SupplyService

pytestmark = [pytest.mark.asyncio, pytest.mark.supplies]


async def _make_supply(db, **kw):
    s = Supply(
        name=kw.get("name", "Oil"),
        unit_type=kw.get("unit_type", "volume"),
        volume_unit=kw.get("volume_unit"),
    )
    db.add(s)
    await db.flush()
    return s


async def test_on_hand_and_avg_cost(db_session):
    svc = SupplyService(db_session)
    s = await _make_supply(db_session)
    db_session.add_all(
        [
            SupplyPurchase(
                supply_id=s.id,
                date=date.today(),
                quantity=Decimal("5"),
                total_cost=Decimal("40.00"),
            ),
            SupplyPurchase(
                supply_id=s.id,
                date=date.today(),
                quantity=Decimal("5"),
                total_cost=Decimal("50.00"),
            ),
            SupplyUsage(supply_id=s.id, quantity=Decimal("4")),
        ]
    )
    await db_session.flush()
    balances = await svc._compute_balances([s.id])
    on_hand, avg = balances[s.id]
    assert on_hand == Decimal("6.000")  # 10 purchased − 4 used
    assert avg == Decimal("9.0000")  # 90.00 / 10


async def test_avg_cost_ignores_costless_opening_stock(db_session):
    svc = SupplyService(db_session)
    s = await _make_supply(db_session)
    db_session.add_all(
        [
            SupplyPurchase(
                supply_id=s.id, date=date.today(), quantity=Decimal("2"), total_cost=None
            ),  # opening stock, no cost
            SupplyPurchase(
                supply_id=s.id, date=date.today(), quantity=Decimal("1"), total_cost=Decimal("8.00")
            ),
        ]
    )
    await db_session.flush()
    on_hand, avg = (await svc._compute_balances([s.id]))[s.id]
    assert on_hand == Decimal("3.000")  # both count toward on-hand
    assert avg == Decimal("8.0000")  # only the costed 1 unit divides the cost


async def test_negative_on_hand_allowed(db_session):
    svc = SupplyService(db_session)
    s = await _make_supply(db_session)
    db_session.add(SupplyUsage(supply_id=s.id, quantity=Decimal("2")))
    await db_session.flush()
    on_hand, avg = (await svc._compute_balances([s.id]))[s.id]
    assert on_hand == Decimal("-2.000")
    assert avg is None


async def test_delete_archives_when_history_exists(db_session):
    svc = SupplyService(db_session)
    s = await _make_supply(db_session)
    db_session.add(SupplyPurchase(supply_id=s.id, date=date.today(), quantity=Decimal("1")))
    await db_session.flush()
    archived = await svc.delete_supply(s.id, None)
    assert archived is True
    refetched = await svc.get_supply(s.id)
    assert refetched.is_active is False


async def test_delete_hard_deletes_when_no_history(db_session):
    from fastapi import HTTPException

    svc = SupplyService(db_session)
    s = await _make_supply(db_session)
    archived = await svc.delete_supply(s.id, None)
    assert archived is False
    with pytest.raises(HTTPException):
        await svc.get_supply(s.id)


async def test_create_and_response_carry_the_unit(db_session):
    svc = SupplyService(db_session)
    created = await svc.create_supply(
        SupplyCreate(name="Brake fluid", unit_type="volume", volume_unit="fl_oz_us"), None
    )
    assert created.volume_unit == "fl_oz_us"


async def test_patch_sets_and_clears_the_unit(db_session):
    svc = SupplyService(db_session)
    s = await _make_supply(db_session)
    updated = await svc.update_supply(s.id, SupplyUpdate(volume_unit="qt_uk"), None)
    assert updated.volume_unit == "qt_uk"
    cleared = await svc.update_supply(s.id, SupplyUpdate(volume_unit=None), None)
    assert cleared.volume_unit is None


async def test_patch_unit_onto_a_count_supply_is_422(db_session):
    svc = SupplyService(db_session)
    s = await _make_supply(db_session, unit_type="count")
    with pytest.raises(HTTPException) as e:
        await svc.update_supply(s.id, SupplyUpdate(volume_unit="qt_us"), None)
    assert e.value.status_code == 422
    assert e.value.detail == "A count supply cannot carry a volume unit"


async def test_usage_response_carries_the_owning_supplys_unit(db_session):
    svc = SupplyService(db_session)
    s = await _make_supply(db_session, volume_unit="mL")
    db_session.add(SupplyUsage(supply_id=s.id, quantity=Decimal("2")))
    await db_session.flush()
    usage = (
        await db_session.execute(
            select(SupplyUsage)
            .where(SupplyUsage.supply_id == s.id)
            .options(selectinload(SupplyUsage.supply))
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert svc.to_usage_response(usage).volume_unit == "mL"

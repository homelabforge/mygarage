"""#301: a supply used before it had a costed purchase gets priced later.

A usage freezes its price when it's first saved, at the supply's average over
costed purchases. Before any costed purchase that average is None, so the usage
was saved unpriced (``cost_snapshot`` NULL) and stayed that way forever: the
History card left the parts out while the editor estimated them at today's
average. Now an unpriced usage is priced at the first chance a writer of its
vehicle has: a costed purchase of the supply, or any write to its visit. A
priced usage stays frozen.

The client fixture shares one session across requests, and the purchase prices
in a session of its own, so a test calls ``expire_all()``
before looking at rows the pricing wrote.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.service_visit import ServiceVisit
from app.models.supply import SupplyPurchase, SupplyUsage
from app.models.vehicle import Vehicle
from app.models.vehicle_share import VehicleShare
from app.schemas._money import MONEY_MAX

pytestmark = [pytest.mark.integration, pytest.mark.asyncio, pytest.mark.supplies]

# A visit total with only 1.00 of headroom under the money column.
_NEAR_CAP = str(MONEY_MAX - Decimal("1.00"))

# 5 US quarts, the issue's oil. Quantities are canonical litres on the wire.
FIVE_QT_L = "4.73176473"


async def _bare_supply(client: AsyncClient, headers: dict[str, str], name: str, unit: str) -> int:
    """A supply with no purchase at all, so its average cost is None."""
    r = await client.post("/api/supplies", json={"name": name, "unit_type": unit}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _buy(
    client: AsyncClient,
    headers: dict[str, str],
    sid: int,
    quantity: str,
    total_cost: str | None,
) -> dict[str, Any]:
    body: dict[str, str] = {"date": "2026-11-17", "quantity": quantity}
    if total_cost is not None:
        body["total_cost"] = total_cost
    r = await client.post(f"/api/supplies/{sid}/purchases", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def _visit(
    client: AsyncClient,
    headers: dict[str, str],
    vin: str,
    uses: list[tuple[int, str]],
    labour: str = "35.95",
    fees: dict[str, str] | None = None,
) -> dict[str, Any]:
    r = await client.post(
        f"/api/vehicles/{vin}/service-visits",
        json={
            "date": "2026-11-17",
            "service_category": "Maintenance",
            **(fees or {}),
            "line_items": [
                {
                    "description": "The Works Package",
                    "cost": labour,
                    "supplies_used": [{"supply_id": s, "quantity": q} for s, q in uses],
                }
            ],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


@dataclass(frozen=True)
class Use:
    """A usage row's values, read out so a later expire_all can't touch them."""

    id: int
    service_line_item_id: int | None
    unit_cost_snapshot: Decimal | None
    cost_snapshot: Decimal | None


async def _usages(db: AsyncSession, sid: int) -> list[Use]:
    db.expire_all()
    rows = await db.execute(
        select(
            SupplyUsage.id,
            SupplyUsage.service_line_item_id,
            SupplyUsage.unit_cost_snapshot,
            SupplyUsage.cost_snapshot,
        )
        .where(SupplyUsage.supply_id == sid)
        .order_by(SupplyUsage.id)
    )
    return [Use(*row) for row in rows.all()]


async def _stored_total(db: AsyncSession, visit_id: int) -> Decimal | None:
    db.expire_all()
    return (
        await db.execute(select(ServiceVisit.total_cost).where(ServiceVisit.id == visit_id))
    ).scalar_one()


async def _get_visit(
    client: AsyncClient, headers: dict[str, str], vin: str, visit_id: int
) -> dict[str, Any]:
    r = await client.get(f"/api/vehicles/{vin}/service-visits/{visit_id}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def test_issue_301_purchase_prices_the_visit(
    client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
):
    """The issue's own numbers: logged first, invoice purchases entered after."""
    vin = test_vehicle["vin"]
    oil = await _bare_supply(client, auth_headers, "Motorcraft 5W-20", "volume")
    kit = await _bare_supply(client, auth_headers, "Motorcraft Filter Kit", "count")
    visit = await _visit(
        client,
        auth_headers,
        vin,
        [(oil, FIVE_QT_L), (kit, "1")],
        fees={"tax_amount": "4.11", "shop_supplies": "4.94", "misc_fees": "1.00"},
    )
    assert Decimal(visit["calculated_total_cost"]) == Decimal("46.00")  # the bug, before

    await _buy(client, auth_headers, oil, FIVE_QT_L, "37.45")
    await _buy(client, auth_headers, kit, "1", "9.00")

    [oil_use] = await _usages(db_session, oil)
    [kit_use] = await _usages(db_session, kit)
    assert oil_use.unit_cost_snapshot == Decimal("7.9146")
    assert oil_use.cost_snapshot == Decimal("37.45")
    assert kit_use.unit_cost_snapshot == Decimal("9.0000")
    assert kit_use.cost_snapshot == Decimal("9.00")
    assert await _stored_total(db_session, visit["id"]) == Decimal("92.45")
    body = await _get_visit(client, auth_headers, vin, visit["id"])
    assert Decimal(body["parts_supplies_cost"]) == Decimal("46.45")
    assert Decimal(body["calculated_total_cost"]) == Decimal("92.45")


async def test_priced_usage_stays_frozen_on_a_later_purchase(
    client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
):
    vin = test_vehicle["vin"]
    sid = await _bare_supply(client, auth_headers, "Oil", "volume")
    await _buy(client, auth_headers, sid, "10", "80.00")  # avg 8.00
    visit = await _visit(client, auth_headers, vin, [(sid, "5")], labour="0")
    await _buy(client, auth_headers, sid, "10", "200.00")  # avg now 14.00
    [use] = await _usages(db_session, sid)
    assert use.cost_snapshot == Decimal("40.00")
    assert await _stored_total(db_session, visit["id"]) == Decimal("40.00")


async def test_zero_cost_purchase_prices_at_zero(
    client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
):
    """Free stock is a known cost of 0.00, not an unknown one."""
    sid = await _bare_supply(client, auth_headers, "Sample oil", "volume")
    await _visit(client, auth_headers, test_vehicle["vin"], [(sid, "1")], labour="0")
    await _buy(client, auth_headers, sid, "5", "0")
    [use] = await _usages(db_session, sid)
    assert use.unit_cost_snapshot == Decimal("0")
    assert use.cost_snapshot == Decimal("0")


async def test_uncosted_purchase_prices_nothing(
    client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
):
    sid = await _bare_supply(client, auth_headers, "Oil", "volume")
    await _visit(client, auth_headers, test_vehicle["vin"], [(sid, "1")], labour="0")
    await _buy(client, auth_headers, sid, "5", None)
    [use] = await _usages(db_session, sid)
    assert use.unit_cost_snapshot is None
    assert use.cost_snapshot is None


async def _seed_usage_states(
    client: AsyncClient, headers: dict[str, str], vin: str, db: AsyncSession
) -> tuple[int, int, int]:
    """A supply with three usages on one visit, then two of them rewritten the
    way an import can leave them: cost only, and unit only."""
    sid = await _bare_supply(client, headers, "Oil", "volume")
    visit = await _visit(client, headers, vin, [(sid, "2")], labour="0")
    item_id = visit["line_items"][0]["id"]
    db.expire_all()
    unit_only = (
        await db.execute(select(SupplyUsage).where(SupplyUsage.supply_id == sid))
    ).scalar_one()
    unit_only.unit_cost_snapshot = Decimal("5.0000")
    cost_only = SupplyUsage(
        supply_id=sid,
        service_line_item_id=item_id,
        quantity=Decimal("3"),
        unit_cost_snapshot=None,
        cost_snapshot=Decimal("12.00"),
    )
    db.add(cost_only)
    await db.flush()
    ids = (unit_only.id, cost_only.id)
    await db.commit()
    return sid, *ids


async def test_import_shaped_rows(
    client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
):
    """A cost-only row is priced and never touched; a unit-only row gets its cost
    from its own frozen unit, not the new average."""
    sid, unit_only_id, cost_only_id = await _seed_usage_states(
        client, auth_headers, test_vehicle["vin"], db_session
    )
    await _buy(client, auth_headers, sid, "10", "80.00")  # avg 8.00
    rows = {u.id: u for u in await _usages(db_session, sid)}
    assert rows[unit_only_id].unit_cost_snapshot == Decimal("5.0000")
    assert rows[unit_only_id].cost_snapshot == Decimal("10.00")
    assert rows[cost_only_id].unit_cost_snapshot is None
    assert rows[cost_only_id].cost_snapshot == Decimal("12.00")


async def test_deleting_the_purchase_keeps_the_price(
    client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
):
    sid = await _bare_supply(client, auth_headers, "Oil", "volume")
    await _visit(client, auth_headers, test_vehicle["vin"], [(sid, "5")], labour="0")
    purchase = await _buy(client, auth_headers, sid, "10", "80.00")
    r = await client.delete(f"/api/supplies/{sid}/purchases/{purchase['id']}", headers=auth_headers)
    assert r.status_code == 204
    [use] = await _usages(db_session, sid)
    assert use.cost_snapshot == Decimal("40.00")


async def test_standalone_adjustment_gets_priced(
    client: AsyncClient, auth_headers, db_session: AsyncSession
):
    sid = await _bare_supply(client, auth_headers, "Coolant", "volume")
    r = await client.post(
        f"/api/supplies/{sid}/adjustments", json={"quantity": "2"}, headers=auth_headers
    )
    assert r.status_code in (200, 201), r.text
    await _buy(client, auth_headers, sid, "4", "30.00")  # avg 7.50
    [use] = await _usages(db_session, sid)
    assert use.service_line_item_id is None
    assert use.cost_snapshot == Decimal("15.00")
    history = (await client.get(f"/api/supplies/{sid}/history", headers=auth_headers)).json()
    adjustment = next(
        e for e in history["entries"] if e["id"] == use.id and Decimal(e["quantity"]) < 0
    )
    assert Decimal(adjustment["cost"]) == Decimal("15.00")


async def _shared_vehicle(
    db: AsyncSession, owner_id: object, vin: str, user_id: object, permission: str
) -> None:
    db.add(Vehicle(vin=vin, user_id=owner_id, nickname=vin, vehicle_type="Car"))
    await db.flush()
    db.add(
        VehicleShare(vehicle_vin=vin, user_id=user_id, permission=permission, shared_by=owner_id)
    )
    await db.commit()


async def test_purchase_prices_only_vehicles_the_buyer_can_write(
    client: AsyncClient,
    auth_headers,
    non_admin_headers,
    test_user,
    non_admin_user,
    db_session: AsyncSession,
):
    """A household purchase must not write another vehicle's history for someone
    who can only read it. That vehicle waits for one of its writers."""
    writable, readable = "PRICEWRITE0000001", "PRICEREAD00000001"
    await _shared_vehicle(db_session, test_user["id"], writable, non_admin_user["id"], "write")
    await _shared_vehicle(db_session, test_user["id"], readable, non_admin_user["id"], "read")
    try:
        sid = await _bare_supply(client, auth_headers, "Oil", "volume")
        a = await _visit(client, auth_headers, writable, [(sid, "1")], labour="0")
        b = await _visit(client, auth_headers, readable, [(sid, "1")], labour="0")

        await _buy(client, non_admin_headers, sid, "10", "80.00")

        assert await _stored_total(db_session, a["id"]) == Decimal("8.00")
        assert await _stored_total(db_session, b["id"]) == Decimal("0.00")
        by_visit = {u.service_line_item_id: u for u in await _usages(db_session, sid)}
        assert by_visit[b["line_items"][0]["id"]].cost_snapshot is None

        # The readable vehicle's owner touches its visit: now it's priced.
        r = await client.put(
            f"/api/vehicles/{readable}/service-visits/{b['id']}",
            json={"notes": "invoice filed"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        assert Decimal(r.json()["calculated_total_cost"]) == Decimal("8.00")
    finally:
        await db_session.rollback()
        for vin in (writable, readable):
            stored = await db_session.get(Vehicle, vin)
            if stored is not None:
                await db_session.delete(stored)
        await db_session.commit()


async def test_overflowing_visit_is_skipped_and_others_priced(
    client: AsyncClient, auth_headers, test_vehicle, own_vehicle, db_session: AsyncSession
):
    """Pricing that would push one visit past the money column leaves that visit
    alone; the purchase and every other visit go through."""
    sid = await _bare_supply(client, auth_headers, "Oil", "volume")
    huge = await _visit(client, auth_headers, own_vehicle.vin, [(sid, "5")], labour=_NEAR_CAP)
    normal = await _visit(client, auth_headers, test_vehicle["vin"], [(sid, "5")], labour="0")

    await _buy(client, auth_headers, sid, "10", "80.00")  # 5 × 8.00 = 40.00 > 1.00 headroom

    assert await _stored_total(db_session, huge["id"]) == Decimal(_NEAR_CAP)
    assert await _stored_total(db_session, normal["id"]) == Decimal("40.00")
    by_item = {u.service_line_item_id: u for u in await _usages(db_session, sid)}
    assert by_item[huge["line_items"][0]["id"]].cost_snapshot is None


@pytest.mark.parametrize("failure", ["error", "lock_busy"])
async def test_one_vehicle_failing_never_fails_the_purchase(
    client: AsyncClient,
    auth_headers,
    test_vehicle,
    own_vehicle,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
):
    """The purchase is committed before pricing starts, so its answer must say so:
    a 500 here would have the user enter it twice."""
    from fastapi import HTTPException

    from app.services import supply_pricing

    # Vehicles go in VIN order, so the broken one ("1HGB...") goes first and the
    # fine one ("LEG...") proves the loop carried on past it.
    sid = await _bare_supply(client, auth_headers, "Oil", "volume")
    broken_vin, fine_vin = test_vehicle["vin"], own_vehicle.vin
    assert broken_vin < fine_vin
    broken = await _visit(client, auth_headers, broken_vin, [(sid, "5")], labour="0")
    fine = await _visit(client, auth_headers, fine_vin, [(sid, "5")], labour="0")

    real_lock: Callable[[AsyncSession, str], Awaitable[None]] = (
        supply_pricing.lock_vehicle_for_write
    )

    async def flaky_lock(db: AsyncSession, vin: str) -> None:
        if vin == broken_vin:
            if failure == "lock_busy":
                raise HTTPException(status_code=503, detail="busy")
            raise RuntimeError("boom")
        await real_lock(db, vin)

    monkeypatch.setattr(supply_pricing, "lock_vehicle_for_write", flaky_lock)
    purchase = await _buy(client, auth_headers, sid, "10", "80.00")

    assert Decimal(purchase["total_cost"]) == Decimal("80.00")
    assert await _stored_total(db_session, broken["id"]) == Decimal("0.00")
    assert await _stored_total(db_session, fine["id"]) == Decimal("40.00")


@pytest.mark.parametrize("buyer", ["gone", "inactive"])
async def test_a_buyer_gone_or_inactive_prices_nothing(
    client: AsyncClient,
    auth_headers,
    test_vehicle,
    test_user,
    non_admin_user,
    db_session: AsyncSession,
    buyer: str,
):
    """No buyer reads as auth off, where every vehicle passes, so a buyer gone
    by the time pricing runs must stop it, not price as nobody."""
    from app.models.user import User
    from app.services import supply_pricing

    vin = test_vehicle["vin"]
    sid = await _bare_supply(client, auth_headers, "Oil", "volume")
    visit = await _visit(client, auth_headers, vin, [(sid, "5")], labour="0")
    r = await client.post(
        f"/api/supplies/{sid}/adjustments", json={"quantity": "2"}, headers=auth_headers
    )
    assert r.status_code in (200, 201), r.text
    db_session.add(
        SupplyPurchase(
            supply_id=sid, date=date(2026, 11, 17), quantity=Decimal("10"), total_cost=Decimal("80")
        )
    )
    if buyer == "gone":
        user_id = 2_000_000_000
    else:
        # A writer of the vehicle, so only being inactive stops it.
        user_id = non_admin_user["id"]
        db_session.add(
            VehicleShare(
                vehicle_vin=vin, user_id=user_id, permission="write", shared_by=test_user["id"]
            )
        )
        await db_session.execute(update(User).where(User.id == user_id).values(is_active=False))
    await db_session.commit()

    await supply_pricing.price_after_purchase(db_session, sid, user_id)

    assert [u.cost_snapshot for u in await _usages(db_session, sid)] == [None, None]
    assert await _stored_total(db_session, visit["id"]) == Decimal("0.00")
    # Auth off prices them both: the visit's 5 and the 2 spilled, at 8.00.
    await supply_pricing.price_after_purchase(db_session, sid, None)
    assert [u.cost_snapshot for u in await _usages(db_session, sid)] == [
        Decimal("40.00"),
        Decimal("16.00"),
    ]


async def test_a_purchase_gives_its_connection_back_before_pricing(
    client: AsyncClient,
    auth_headers,
    test_vehicle,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """Pricing takes a connection of its own. Still holding the request's, a
    full pool would leave every costed purchase waiting on itself."""
    from app.services import supply_pricing

    real = supply_pricing._own_session
    holding: list[bool] = []

    def spy(request_db: AsyncSession) -> AsyncSession:
        holding.append(request_db.in_transaction())
        return real(request_db)

    monkeypatch.setattr(supply_pricing, "_own_session", spy)
    sid = await _bare_supply(client, auth_headers, "Oil", "volume")
    visit = await _visit(client, auth_headers, test_vehicle["vin"], [(sid, "5")], labour="0")

    await _buy(client, auth_headers, sid, "10", "80.00")

    assert holding == [False]
    assert await _stored_total(db_session, visit["id"]) == Decimal("40.00")


# ---- visit writes price unpriced usages (opportunity 2) ---------------------


async def _unpriced_then_costed(
    client: AsyncClient,
    headers: dict[str, str],
    vin: str,
    db: AsyncSession,
    labour: str = "0",
) -> dict[str, Any]:
    """A visit with an unpriced usage of a supply that has since gained a costed
    purchase, written straight to the table (like an import) so the purchase
    trigger never ran. avg 8.00, 5 used: 40.00 once priced."""
    sid = await _bare_supply(client, headers, "Oil", "volume")
    visit = await _visit(client, headers, vin, [(sid, "5")], labour=labour)
    db.add(
        SupplyPurchase(
            supply_id=sid, date=date(2026, 11, 17), quantity=Decimal("10"), total_cost=Decimal("80")
        )
    )
    await db.commit()
    return visit


async def test_notes_only_edit_prices(
    client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
):
    vin = test_vehicle["vin"]
    visit = await _unpriced_then_costed(client, auth_headers, vin, db_session)
    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit['id']}",
        json={"notes": "filed"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["parts_supplies_cost"]) == Decimal("40.00")
    assert await _stored_total(db_session, visit["id"]) == Decimal("40.00")


async def test_line_item_edit_without_supplies_prices(
    client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
):
    """A PUT whose line items leave out supplies_used keeps the usages; it prices them too."""
    vin = test_vehicle["vin"]
    visit = await _unpriced_then_costed(client, auth_headers, vin, db_session)
    item = visit["line_items"][0]
    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit['id']}",
        json={"line_items": [{"id": item["id"], "description": "Oil change", "cost": "0"}]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["calculated_total_cost"]) == Decimal("40.00")


async def test_adding_a_line_item_prices(
    client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
):
    vin = test_vehicle["vin"]
    visit = await _unpriced_then_costed(client, auth_headers, vin, db_session)
    r = await client.post(
        f"/api/vehicles/{vin}/service-visits/{visit['id']}/line-items",
        json={"description": "Wiper blades", "cost": "20.00"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    assert await _stored_total(db_session, visit["id"]) == Decimal("60.00")


async def test_deleting_another_line_item_prices(
    client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
):
    vin = test_vehicle["vin"]
    visit = await _unpriced_then_costed(client, auth_headers, vin, db_session)
    extra = await client.post(
        f"/api/vehicles/{vin}/service-visits/{visit['id']}/line-items",
        json={"description": "Wiper blades", "cost": "20.00"},
        headers=auth_headers,
    )
    # Adding priced it already; put it back to unpriced to test the delete alone.
    db_session.expire_all()
    await db_session.execute(
        update(SupplyUsage)
        .where(SupplyUsage.service_line_item_id == visit["line_items"][0]["id"])
        .values(unit_cost_snapshot=None, cost_snapshot=None)
    )
    await db_session.commit()
    r = await client.delete(
        f"/api/vehicles/{vin}/service-visits/{visit['id']}/line-items/{extra.json()['id']}",
        headers=auth_headers,
    )
    assert r.status_code == 204, r.text
    assert await _stored_total(db_session, visit["id"]) == Decimal("40.00")


async def test_pricing_that_would_overflow_never_blocks_the_edit(
    client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
):
    """The edit fits on its own; pricing would push it over. The edit saves, unpriced."""
    vin = test_vehicle["vin"]
    visit = await _unpriced_then_costed(client, auth_headers, vin, db_session, labour=_NEAR_CAP)
    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit['id']}",
        json={"notes": "filed"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["notes"] == "filed"
    assert Decimal(r.json()["calculated_total_cost"]) == Decimal(_NEAR_CAP)
    [use] = await _usages(
        db_session, int(r.json()["line_items"][0]["supply_usages"][0]["supply_id"])
    )
    assert use.cost_snapshot is None


async def test_an_edit_that_overflows_alone_is_still_refused(
    client: AsyncClient, auth_headers, test_vehicle, db_session: AsyncSession
):
    vin = test_vehicle["vin"]
    visit = await _unpriced_then_costed(client, auth_headers, vin, db_session)
    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit['id']}",
        json={"tax_amount": str(MONEY_MAX)},  # 40.00 of parts + this is past the cap
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text  # pricing is skipped; the edit alone fits
    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit['id']}",
        json={"shop_supplies": "1.00"},  # now the edit itself passes the cap
        headers=auth_headers,
    )
    assert r.status_code == 422, r.text


async def test_completing_a_reminder_onto_the_visit_prices(
    client: AsyncClient, auth_headers, own_vehicle, db_session: AsyncSession
):
    """Linking a reminder's completion to the visit adds a line item there: a visit write."""
    vin = own_vehicle.vin
    visit = await _unpriced_then_costed(client, auth_headers, vin, db_session)
    r = await client.post(
        f"/api/vehicles/{vin}/reminders/apply-pack",
        json={"pack_id": "oil_and_filter"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    reminders = (await client.get(f"/api/vehicles/{vin}/reminders", headers=auth_headers)).json()
    [oil] = [x for x in reminders if x["maintenance_type"] == "engine_oil_filter"]
    r = await client.post(
        f"/api/vehicles/{vin}/reminders/{oil['id']}/complete",
        json={
            "completed_date": "2026-11-17",
            "mode": "link_visit",
            "service_visit_id": visit["id"],
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert await _stored_total(db_session, visit["id"]) == Decimal("40.00")

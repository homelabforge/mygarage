"""#307: a visit's supplies are priced as of the visit's date.

A usage on a visit takes the weighted average of its supply's costed purchases
dated on or before the visit. With none there it takes the all-time average and
is flagged ``cost_estimated``, so #301 still holds: a receipt entered after an
old visit prices it, flagged, not at nothing. An estimate settles once a costed
purchase on or before its visit shows up, and only then: a later receipt never
moves it. Changing a visit's date re-prices each usage whose on/before set of
purchases changed.

The numbers are migration 163's: a July 2025 purchase of 5 for $30.00, a June
2026 purchase of 5 for $37.45, and a visit on 2025-07-17 that uses 5, with
$72.24 of other costs. Resolved, that visit is $102.24; stuck on the June
price it was $109.69.

The client fixture shares one session across requests, and a purchase prices
in a session of its own, so reads go through the API or after ``expire_all()``.
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

JULY_2025 = "2025-07-10"
VISIT_DAY = "2025-07-17"
JUNE_2026 = "2026-06-02"
LABOUR = "72.24"


async def _supply(client: AsyncClient, headers: dict[str, str]) -> int:
    r = await client.post(
        "/api/supplies", json={"name": "Motorcraft 5W-20", "unit_type": "volume"}, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _buy(
    client: AsyncClient,
    headers: dict[str, str],
    sid: int,
    day: str,
    total_cost: str,
    qty: str = "5",
) -> int:
    r = await client.post(
        f"/api/supplies/{sid}/purchases",
        json={"date": day, "quantity": qty, "total_cost": total_cost},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _unbuy(client: AsyncClient, headers: dict[str, str], sid: int, purchase_id: int) -> None:
    r = await client.delete(f"/api/supplies/{sid}/purchases/{purchase_id}", headers=headers)
    assert r.status_code == 204, r.text


async def _visit(
    client: AsyncClient,
    headers: dict[str, str],
    vin: str,
    day: str,
    sid: int,
    labour: str = LABOUR,
) -> int:
    r = await client.post(
        f"/api/vehicles/{vin}/service-visits",
        json={
            "date": day,
            "service_category": "Maintenance",
            "line_items": [
                {
                    "description": "Oil change",
                    "cost": labour,
                    "supplies_used": [{"supply_id": sid, "quantity": "5"}],
                }
            ],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _move(
    client: AsyncClient, headers: dict[str, str], vin: str, visit_id: int, day: str
) -> Any:
    return await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit_id}", json={"date": day}, headers=headers
    )


@dataclass(frozen=True)
class Seen:
    """A visit's one usage as the API shows it, and the visit's totals."""

    unit: Decimal | None
    cost: Decimal | None
    estimated: bool
    total: Decimal
    stored_total: Decimal | None


async def _seen(
    client: AsyncClient, headers: dict[str, str], db: AsyncSession, vin: str, visit_id: int
) -> Seen:
    # The pricers write in sessions of their own; the shared one must reload.
    db.expire_all()
    r = await client.get(f"/api/vehicles/{vin}/service-visits/{visit_id}", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    [use] = body["line_items"][0]["supply_usages"]
    stored = (
        await db.execute(select(ServiceVisit.total_cost).where(ServiceVisit.id == visit_id))
    ).scalar_one()
    return Seen(
        unit=None if use["unit_cost_snapshot"] is None else Decimal(use["unit_cost_snapshot"]),
        cost=None if use["cost_snapshot"] is None else Decimal(use["cost_snapshot"]),
        estimated=use["cost_estimated"],
        total=Decimal(body["calculated_total_cost"]),
        stored_total=stored,
    )


async def _expect(
    client: AsyncClient,
    headers: dict[str, str],
    db: AsyncSession,
    vin: str,
    visit_id: int,
    cost: str | None,
    estimated: bool,
    total: str,
) -> None:
    seen = await _seen(client, headers, db, vin, visit_id)
    assert (seen.cost, seen.estimated, seen.total) == (
        None if cost is None else Decimal(cost),
        estimated,
        Decimal(total),
    )
    # The cached total follows every re-price (regression control).
    assert seen.stored_total == seen.total


async def _history_flags(
    client: AsyncClient, headers: dict[str, str], db: AsyncSession, sid: int
) -> list[bool]:
    db.expire_all()
    r = await client.get(f"/api/supplies/{sid}/history", headers=headers)
    assert r.status_code == 200, r.text
    return [e["cost_estimated"] for e in r.json()["entries"] if e["entry_type"] == "usage"]


# ---- the flag on the wire ----------------------------------------------------


async def test_both_responses_carry_the_flag(
    client: AsyncClient, auth_headers, own_vehicle: Vehicle, db_session: AsyncSession
):
    """The visit's usage and the supply's history entry both say it's an estimate."""
    vin = own_vehicle.vin
    sid = await _supply(client, auth_headers)
    visit = await _visit(client, auth_headers, vin, VISIT_DAY, sid)
    assert await _history_flags(client, auth_headers, db_session, sid) == [False]
    db_session.expire_all()
    await db_session.execute(
        update(SupplyUsage)
        .where(SupplyUsage.supply_id == sid)
        .values(
            unit_cost_snapshot=Decimal("7.4900"),
            cost_snapshot=Decimal("37.45"),
            cost_estimated=True,
        )
    )
    await db_session.execute(
        update(ServiceVisit).where(ServiceVisit.id == visit).values(total_cost=Decimal("109.69"))
    )
    await db_session.commit()
    await _expect(client, auth_headers, db_session, vin, visit, "37.45", True, "109.69")
    assert await _history_flags(client, auth_headers, db_session, sid) == [True]
    r = await client.get(f"/api/vehicles/{vin}/supply-usages", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert [u["cost_estimated"] for u in r.json()["usages"]] == [True]


# ---- the snapshot at save time ----------------------------------------------


async def test_a_visit_saved_after_only_later_receipts_is_flagged(
    client: AsyncClient, auth_headers, own_vehicle: Vehicle, db_session: AsyncSession
):
    """The snapshot at save time follows the same rule as the pricers."""
    vin = own_vehicle.vin
    sid = await _supply(client, auth_headers)
    await _buy(client, auth_headers, sid, JUNE_2026, "37.45")
    visit = await _visit(client, auth_headers, vin, VISIT_DAY, sid)
    await _expect(client, auth_headers, db_session, vin, visit, "37.45", True, "109.69")


async def test_a_purchase_on_or_before_the_visit_is_not_an_estimate(
    client: AsyncClient, auth_headers, own_vehicle: Vehicle, db_session: AsyncSession
):
    vin = own_vehicle.vin
    sid = await _supply(client, auth_headers)
    await _buy(client, auth_headers, sid, JULY_2025, "30.00")
    visit = await _visit(client, auth_headers, vin, VISIT_DAY, sid)
    await _expect(client, auth_headers, db_session, vin, visit, "30.00", False, "102.24")
    assert await _history_flags(client, auth_headers, db_session, sid) == [False]


async def test_a_visit_saved_between_two_receipts_prices_as_of_its_date(
    client: AsyncClient, auth_headers, own_vehicle: Vehicle, db_session: AsyncSession
):
    """The June receipt is after the visit, so only July's counts: 30.00, not 33.73."""
    vin = own_vehicle.vin
    sid = await _supply(client, auth_headers)
    await _buy(client, auth_headers, sid, JULY_2025, "30.00")
    await _buy(client, auth_headers, sid, JUNE_2026, "37.45")
    visit = await _visit(client, auth_headers, vin, VISIT_DAY, sid)
    await _expect(client, auth_headers, db_session, vin, visit, "30.00", False, "102.24")


# ---- the reporter's order and #301: purchases settle estimates --------------


async def test_reporters_order_settles_at_the_july_price(
    client: AsyncClient, auth_headers, own_vehicle: Vehicle, db_session: AsyncSession
):
    """Visit logged unpriced, June 2026 receipt, then the backdated July 2025 one."""
    vin = own_vehicle.vin
    sid = await _supply(client, auth_headers)
    old = await _visit(client, auth_headers, vin, VISIT_DAY, sid)
    await _expect(client, auth_headers, db_session, vin, old, None, False, LABOUR)

    await _buy(client, auth_headers, sid, JUNE_2026, "37.45")
    await _expect(client, auth_headers, db_session, vin, old, "37.45", True, "109.69")
    assert await _history_flags(client, auth_headers, db_session, sid) == [True]

    # A visit after the June receipt prices from it, for real.
    june = await _visit(client, auth_headers, vin, "2026-06-05", sid, labour="0")
    await _expect(client, auth_headers, db_session, vin, june, "37.45", False, "37.45")

    await _buy(client, auth_headers, sid, JULY_2025, "30.00")
    await _expect(client, auth_headers, db_session, vin, old, "30.00", False, "102.24")
    seen = await _seen(client, auth_headers, db_session, vin, old)
    assert seen.unit == Decimal("6.0000")
    # Frozen and real: the backdated receipt doesn't move it (regression control).
    await _expect(client, auth_headers, db_session, vin, june, "37.45", False, "37.45")
    assert await _history_flags(client, auth_headers, db_session, sid) == [False, False]


async def test_a_later_only_receipt_prices_and_flags(
    client: AsyncClient, auth_headers, own_vehicle: Vehicle, db_session: AsyncSession
):
    """#301 still holds: priced from the later receipt, not left at nothing, but flagged."""
    vin = own_vehicle.vin
    sid = await _supply(client, auth_headers)
    visit = await _visit(client, auth_headers, vin, VISIT_DAY, sid)
    await _buy(client, auth_headers, sid, JUNE_2026, "37.45")
    await _expect(client, auth_headers, db_session, vin, visit, "37.45", True, "109.69")


async def test_a_free_purchase_on_the_visit_date_prices_at_zero(
    client: AsyncClient, auth_headers, own_vehicle: Vehicle, db_session: AsyncSession
):
    """On the visit's own date counts as on or before it, and 0.00 is a real price."""
    vin = own_vehicle.vin
    sid = await _supply(client, auth_headers)
    visit = await _visit(client, auth_headers, vin, VISIT_DAY, sid)
    await _buy(client, auth_headers, sid, VISIT_DAY, "0")
    await _expect(client, auth_headers, db_session, vin, visit, "0.00", False, LABOUR)


async def test_a_second_later_receipt_does_not_move_an_estimate(
    client: AsyncClient, auth_headers, own_vehicle: Vehicle, db_session: AsyncSession
):
    """F-2: estimates don't drift with every new receipt."""
    vin = own_vehicle.vin
    sid = await _supply(client, auth_headers)
    visit = await _visit(client, auth_headers, vin, VISIT_DAY, sid)
    await _buy(client, auth_headers, sid, JUNE_2026, "37.45")
    await _buy(client, auth_headers, sid, "2026-09-01", "50.00")
    await _expect(client, auth_headers, db_session, vin, visit, "37.45", True, "109.69")


async def test_a_frozen_price_ignores_a_backdated_purchase(
    client: AsyncClient, auth_headers, own_vehicle: Vehicle, db_session: AsyncSession
):
    """Regression control: a real (unflagged) price stays frozen."""
    vin = own_vehicle.vin
    sid = await _supply(client, auth_headers)
    await _buy(client, auth_headers, sid, JULY_2025, "30.00")
    visit = await _visit(client, auth_headers, vin, VISIT_DAY, sid)
    await _buy(client, auth_headers, sid, "2025-07-01", "100.00")
    await _expect(client, auth_headers, db_session, vin, visit, "30.00", False, "102.24")


# ---- the other pricers pick up a resolvable estimate (D8) -------------------


async def _estimate_with_an_earlier_purchase(
    client: AsyncClient, headers: dict[str, str], vin: str, db: AsyncSession
) -> tuple[int, int, SupplyUsage]:
    """A visit flagged at the June price, then a July receipt written straight
    to the table (as an import or an unwritable vehicle leaves it), so no
    purchase hook ran.

    Also hands back the usage as the shared session loaded it while still
    unpriced: the June pricing wrote it from another session, so the copy in
    this one is stale for as long as the test holds it."""
    sid = await _supply(client, headers)
    visit = await _visit(client, headers, vin, VISIT_DAY, sid)
    held = (await db.execute(select(SupplyUsage).where(SupplyUsage.supply_id == sid))).scalar_one()
    assert held.cost_snapshot is None
    await _buy(client, headers, sid, JUNE_2026, "37.45")
    db.add(
        SupplyPurchase(
            supply_id=sid,
            date=date(2025, 7, 10),
            quantity=Decimal("5"),
            total_cost=Decimal("30.00"),
        )
    )
    await db.commit()
    return sid, visit, held


async def test_any_visit_write_settles_a_resolvable_estimate(
    client: AsyncClient, auth_headers, own_vehicle: Vehicle, db_session: AsyncSession
):
    vin = own_vehicle.vin
    _sid, visit, _held = await _estimate_with_an_earlier_purchase(
        client, auth_headers, vin, db_session
    )
    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit}",
        json={"notes": "filed"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    await _expect(client, auth_headers, db_session, vin, visit, "30.00", False, "102.24")


async def test_import_pricing_settles_a_resolvable_estimate(
    client: AsyncClient, auth_headers, own_vehicle: Vehicle, db_session: AsyncSession
):
    from app.services import supply_pricing

    vin = own_vehicle.vin
    _sid, visit, _held = await _estimate_with_an_earlier_purchase(
        client, auth_headers, vin, db_session
    )
    await supply_pricing.price_after_import(db_session, vin, None)
    await _expect(client, auth_headers, db_session, vin, visit, "30.00", False, "102.24")


async def test_a_later_receipt_locks_no_vehicle_with_an_unresolvable_estimate(
    client: AsyncClient,
    auth_headers,
    own_vehicle: Vehicle,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    """N-7: resolvability is in the selector, so a purchase that can't settle
    an estimate doesn't walk and lock its vehicle."""
    from app.services import supply_pricing

    vin = own_vehicle.vin
    sid = await _supply(client, auth_headers)
    await _visit(client, auth_headers, vin, VISIT_DAY, sid)
    await _buy(client, auth_headers, sid, JUNE_2026, "37.45")

    real: Callable[[AsyncSession, str], Awaitable[None]] = supply_pricing.lock_vehicle_for_write
    locked: list[str] = []

    async def spy(db: AsyncSession, locked_vin: str) -> None:
        locked.append(locked_vin)
        await real(db, locked_vin)

    monkeypatch.setattr(supply_pricing, "lock_vehicle_for_write", spy)
    await _buy(client, auth_headers, sid, "2026-09-01", "50.00")
    assert vin not in locked
    # And one that can settle it does.
    await _buy(client, auth_headers, sid, JULY_2025, "30.00")
    assert vin in locked


# ---- visit date changes (F-1) -------------------------------------------------


async def test_f1_order_visit_saved_today_then_backdated(
    client: AsyncClient, auth_headers, own_vehicle: Vehicle, db_session: AsyncSession
):
    """June receipt, the visit saved with a recent date, the date corrected,
    then the July receipt entered."""
    vin = own_vehicle.vin
    sid = await _supply(client, auth_headers)
    await _buy(client, auth_headers, sid, JUNE_2026, "37.45")
    visit = await _visit(client, auth_headers, vin, "2026-11-17", sid)
    await _expect(client, auth_headers, db_session, vin, visit, "37.45", False, "109.69")

    r = await _move(client, auth_headers, vin, visit, VISIT_DAY)
    assert r.status_code == 200, r.text
    await _expect(client, auth_headers, db_session, vin, visit, "37.45", True, "109.69")

    await _buy(client, auth_headers, sid, JULY_2025, "30.00")
    await _expect(client, auth_headers, db_session, vin, visit, "30.00", False, "102.24")


async def _both_purchases(client: AsyncClient, headers: dict[str, str]) -> int:
    sid = await _supply(client, headers)
    await _buy(client, headers, sid, JULY_2025, "30.00")
    await _buy(client, headers, sid, JUNE_2026, "37.45")
    return sid


@pytest.mark.parametrize(
    ("start", "moved_to", "cost", "total"),
    [
        # Later, past the June receipt: both count now, 67.45 over 10.
        (VISIT_DAY, "2026-07-01", "33.73", "105.97"),
        # Later, onto the June receipt's own day: it counts.
        (VISIT_DAY, JUNE_2026, "33.73", "105.97"),
        # Earlier, back before the June receipt.
        ("2026-07-01", VISIT_DAY, "30.00", "102.24"),
        # Earlier, from the June receipt's own day.
        (JUNE_2026, VISIT_DAY, "30.00", "102.24"),
    ],
    ids=["later", "later-onto-purchase-day", "earlier", "earlier-from-purchase-day"],
)
async def test_moving_the_date_past_a_purchase_reprices(
    client: AsyncClient,
    auth_headers,
    own_vehicle: Vehicle,
    db_session: AsyncSession,
    start: str,
    moved_to: str,
    cost: str,
    total: str,
):
    vin = own_vehicle.vin
    sid = await _both_purchases(client, auth_headers)
    visit = await _visit(client, auth_headers, vin, start, sid)
    r = await _move(client, auth_headers, vin, visit, moved_to)
    assert r.status_code == 200, r.text
    await _expect(client, auth_headers, db_session, vin, visit, cost, False, total)


async def test_a_date_edit_clears_the_flag_at_the_same_price(
    client: AsyncClient, auth_headers, own_vehicle: Vehicle, db_session: AsyncSession
):
    """Saved before the only receipt: the fallback is that receipt's price.
    Moved past it, the same price is now a real one."""
    vin = own_vehicle.vin
    sid = await _supply(client, auth_headers)
    await _buy(client, auth_headers, sid, JULY_2025, "30.00")
    visit = await _visit(client, auth_headers, vin, "2025-07-01", sid)
    await _expect(client, auth_headers, db_session, vin, visit, "30.00", True, "102.24")
    r = await _move(client, auth_headers, vin, visit, VISIT_DAY)
    assert r.status_code == 200, r.text
    await _expect(client, auth_headers, db_session, vin, visit, "30.00", False, "102.24")


async def test_a_date_edit_that_changes_no_purchase_set_leaves_the_row(
    client: AsyncClient, auth_headers, own_vehicle: Vehicle, db_session: AsyncSession
):
    """Half-open: a purchase on the earlier of the two dates was on/before both.
    An imported unit of 5.00 shows whether the row was touched."""
    vin = own_vehicle.vin
    sid = await _supply(client, auth_headers)
    await _buy(client, auth_headers, sid, JULY_2025, "30.00")
    visit = await _visit(client, auth_headers, vin, JULY_2025, sid)
    db_session.expire_all()
    await db_session.execute(
        update(SupplyUsage)
        .where(SupplyUsage.supply_id == sid)
        .values(unit_cost_snapshot=Decimal("5.0000"), cost_snapshot=Decimal("25.00"))
    )
    await db_session.execute(
        update(ServiceVisit).where(ServiceVisit.id == visit).values(total_cost=Decimal("97.24"))
    )
    await db_session.commit()
    r = await _move(client, auth_headers, vin, visit, VISIT_DAY)
    assert r.status_code == 200, r.text
    await _expect(client, auth_headers, db_session, vin, visit, "25.00", False, "97.24")


async def test_a_date_edit_reprices_an_imported_unit(
    client: AsyncClient, auth_headers, own_vehicle: Vehicle, db_session: AsyncSession
):
    """N-2: a row carrying a file's own unit is re-priced like any other."""
    vin = own_vehicle.vin
    sid = await _both_purchases(client, auth_headers)
    visit = await _visit(client, auth_headers, vin, VISIT_DAY, sid)
    db_session.expire_all()
    await db_session.execute(
        update(SupplyUsage)
        .where(SupplyUsage.supply_id == sid)
        .values(unit_cost_snapshot=Decimal("5.0000"), cost_snapshot=Decimal("25.00"))
    )
    await db_session.commit()
    r = await _move(client, auth_headers, vin, visit, "2026-07-01")
    assert r.status_code == 200, r.text
    await _expect(client, auth_headers, db_session, vin, visit, "33.73", False, "105.97")


async def test_an_overflowing_date_repricing_refuses_the_edit(
    client: AsyncClient, auth_headers, own_vehicle: Vehicle, db_session: AsyncSession
):
    """N-2: part of the edit, so the PUT is a 422 and the date stays put."""
    vin = own_vehicle.vin
    sid = await _both_purchases(client, auth_headers)
    labour = str(MONEY_MAX - Decimal("31.00"))
    visit = await _visit(client, auth_headers, vin, VISIT_DAY, sid, labour=labour)
    r = await _move(client, auth_headers, vin, visit, "2026-07-01")  # 33.73 > 31.00
    assert r.status_code == 422, r.text
    r = await client.get(f"/api/vehicles/{vin}/service-visits/{visit}", headers=auth_headers)
    assert r.json()["date"] == VISIT_DAY
    seen = await _seen(client, auth_headers, db_session, vin, visit)
    assert (seen.cost, seen.estimated) == (Decimal("30.00"), False)


async def test_a_date_edit_reprices_at_the_quantity_sent_with_it(
    client: AsyncClient, auth_headers, own_vehicle: Vehicle, db_session: AsyncSession
):
    """The re-price runs after the item sync, so it prices the new quantity."""
    vin = own_vehicle.vin
    sid = await _both_purchases(client, auth_headers)
    visit = await _visit(client, auth_headers, vin, VISIT_DAY, sid)
    item = (await _get(client, auth_headers, vin, visit))["line_items"][0]
    r = await client.put(
        f"/api/vehicles/{vin}/service-visits/{visit}",
        json={
            "date": "2026-07-01",
            "line_items": [
                {
                    "id": item["id"],
                    "description": item["description"],
                    "supplies_used": [{"supply_id": sid, "quantity": "4"}],
                }
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    # 4 at 6.745 = 26.98
    await _expect(client, auth_headers, db_session, vin, visit, "26.98", False, "99.22")


async def _get(
    client: AsyncClient, headers: dict[str, str], vin: str, visit_id: int
) -> dict[str, Any]:
    r = await client.get(f"/api/vehicles/{vin}/service-visits/{visit_id}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# ---- purchase delete (N-6) ----------------------------------------------------


async def test_deleting_a_mistyped_receipt_reruns_the_fallback(
    client: AsyncClient, auth_headers, own_vehicle: Vehicle, db_session: AsyncSession
):
    """$374.50 typed for $37.45, re-entered, then the wrong one deleted."""
    vin = own_vehicle.vin
    sid = await _supply(client, auth_headers)
    visit = await _visit(client, auth_headers, vin, VISIT_DAY, sid)
    wrong = await _buy(client, auth_headers, sid, JUNE_2026, "374.50")
    await _buy(client, auth_headers, sid, JUNE_2026, "37.45")
    await _expect(client, auth_headers, db_session, vin, visit, "374.50", True, "446.74")

    await _unbuy(client, auth_headers, sid, wrong)
    await _expect(client, auth_headers, db_session, vin, visit, "37.45", True, "109.69")


async def test_deleting_the_only_receipt_unprices_the_estimate(
    client: AsyncClient, auth_headers, own_vehicle: Vehicle, db_session: AsyncSession
):
    """The other order: delete first, then re-enter. With no costed purchase
    left there's no fallback, so the estimate goes back to unpriced and the
    re-entered receipt prices it as a first pricing would."""
    vin = own_vehicle.vin
    sid = await _supply(client, auth_headers)
    visit = await _visit(client, auth_headers, vin, VISIT_DAY, sid)
    wrong = await _buy(client, auth_headers, sid, JUNE_2026, "374.50")
    await _unbuy(client, auth_headers, sid, wrong)
    await _expect(client, auth_headers, db_session, vin, visit, None, False, LABOUR)

    await _buy(client, auth_headers, sid, JUNE_2026, "37.45")
    await _expect(client, auth_headers, db_session, vin, visit, "37.45", True, "109.69")


async def test_deleting_a_receipt_leaves_a_real_price_alone(
    client: AsyncClient, auth_headers, own_vehicle: Vehicle, db_session: AsyncSession
):
    """Regression control: only flagged rows re-run the fallback."""
    vin = own_vehicle.vin
    sid = await _supply(client, auth_headers)
    july = await _buy(client, auth_headers, sid, JULY_2025, "30.00")
    visit = await _visit(client, auth_headers, vin, VISIT_DAY, sid)
    await _buy(client, auth_headers, sid, JUNE_2026, "37.45")
    await _unbuy(client, auth_headers, sid, july)
    await _expect(client, auth_headers, db_session, vin, visit, "30.00", False, "102.24")


# ---- write access (regression controls) -------------------------------------


async def test_the_purchase_hooks_respect_the_buyers_write_access(
    client: AsyncClient,
    auth_headers,
    non_admin_headers,
    test_user,
    non_admin_user,
    db_session: AsyncSession,
):
    """Neither a settling purchase nor a delete re-runs anything on a vehicle
    the buyer can only read."""
    vin = "ASOFREAD000000001"
    db_session.add(Vehicle(vin=vin, user_id=test_user["id"], nickname=vin, vehicle_type="Car"))
    await db_session.flush()
    db_session.add(
        VehicleShare(
            vehicle_vin=vin,
            user_id=non_admin_user["id"],
            permission="read",
            shared_by=test_user["id"],
        )
    )
    await db_session.commit()
    try:
        sid = await _supply(client, auth_headers)
        visit = await _visit(client, auth_headers, vin, VISIT_DAY, sid)
        june = await _buy(client, auth_headers, sid, JUNE_2026, "37.45")
        await _expect(client, auth_headers, db_session, vin, visit, "37.45", True, "109.69")

        await _buy(client, non_admin_headers, sid, JULY_2025, "30.00")
        await _expect(client, auth_headers, db_session, vin, visit, "37.45", True, "109.69")
        await _unbuy(client, non_admin_headers, sid, june)
        await _expect(client, auth_headers, db_session, vin, visit, "37.45", True, "109.69")
    finally:
        await db_session.rollback()
        stored = await db_session.get(Vehicle, vin)
        if stored is not None:
            await db_session.delete(stored)
        await db_session.commit()

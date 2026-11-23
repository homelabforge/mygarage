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

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.service_visit import ServiceVisit
from app.models.supply import SupplyUsage
from app.models.vehicle import Vehicle

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
    r = await client.get(f"/api/vehicles/{vin}/service-visits/{visit_id}", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    [use] = body["line_items"][0]["supply_usages"]
    db.expire_all()
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


async def _history_flags(client: AsyncClient, headers: dict[str, str], sid: int) -> list[bool]:
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
    assert await _history_flags(client, auth_headers, sid) == [False]
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
    assert await _history_flags(client, auth_headers, sid) == [True]
    r = await client.get(f"/api/vehicles/{vin}/supply-usages", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert [u["cost_estimated"] for u in r.json()["usages"]] == [True]

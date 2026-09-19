"""Garage analytics and the calendar read household insurance correctly."""

from datetime import timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.insurance import InsurancePolicy, InsurancePolicyVehicle
from app.models.vehicle import Vehicle
from app.utils.household_time import household_today

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

RAM, MIRAGE = "INSCONSUM00000001", "INSCONSUM00000002"


@pytest_asyncio.fixture(autouse=True)
async def garage(db_session: AsyncSession, test_user):
    await db_session.execute(delete(InsurancePolicy))
    for vin, nickname in ((RAM, "Ram"), (MIRAGE, "Mirage")):
        if (await db_session.execute(select(Vehicle).where(Vehicle.vin == vin))).first() is None:
            db_session.add(
                Vehicle(vin=vin, user_id=test_user["id"], nickname=nickname, vehicle_type="Car")
            )
    await db_session.commit()
    yield
    await db_session.execute(delete(InsurancePolicy))
    await db_session.execute(delete(Vehicle).where(Vehicle.vin.in_([RAM, MIRAGE])))
    await db_session.commit()


def _policy(
    days_in: int, term_days: int, premium: str, frequency: str, shares: dict
) -> InsurancePolicy:
    today = household_today()
    start = today - timedelta(days=days_in)
    policy = InsurancePolicy(
        provider="Progressive",
        policy_number="P-A",
        start_date=start,
        end_date=start + timedelta(days=term_days),
        premium_amount=Decimal(premium),
        premium_frequency=frequency,
    )
    for vin, share in shares.items():
        policy.vehicle_links.append(
            InsurancePolicyVehicle(
                vin=vin,
                policy_type="Full Coverage",
                premium_share=Decimal(share) if share else None,
            )
        )
    return policy


async def test_each_vehicle_carries_its_own_share_and_the_garage_total_is_their_sum(
    client, db_session, auth_headers
):
    # A finished 182-day semi-annual term: the whole 600 has accrued.
    db_session.add(_policy(200, 182, "600.00", "Semi-Annual", {RAM: "400.00", MIRAGE: "200.00"}))
    await db_session.commit()

    body = (await client.get("/api/analytics/garage", headers=auth_headers)).json()

    by_vin = {v["vin"]: Decimal(v["total_insurance"]) for v in body["cost_by_vehicle"]}
    assert by_vin[RAM] == Decimal("400.00")
    assert by_vin[MIRAGE] == Decimal("200.00")
    ours = by_vin[RAM] + by_vin[MIRAGE]
    assert Decimal(body["total_costs"]["total_insurance"]) >= ours
    assert any(Decimal(m["insurance"]) > 0 for m in body["monthly_trends"])


async def test_a_monthly_premium_counts_every_month_not_once(client, db_session, auth_headers):
    # 365 days in the past, fully elapsed: 12 x 100.
    db_session.add(_policy(400, 365, "100.00", "Monthly", {RAM: ""}))
    await db_session.commit()

    body = (await client.get("/api/analytics/garage", headers=auth_headers)).json()

    ram = next(v for v in body["cost_by_vehicle"] if v["vin"] == RAM)
    assert Decimal(ram["total_insurance"]) == Decimal("1200.00")


async def test_the_calendar_shows_a_household_policy_once(client, db_session, auth_headers):
    today = household_today()
    policy = InsurancePolicy(
        provider="Progressive",
        policy_number="P-CAL",
        start_date=today - timedelta(days=100),
        end_date=today + timedelta(days=20),
    )
    for vin in (RAM, MIRAGE):
        policy.vehicle_links.append(InsurancePolicyVehicle(vin=vin, policy_type="Liability"))
    db_session.add(policy)
    await db_session.commit()

    response = await client.get(
        "/api/calendar",
        params={
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=60)).isoformat(),
            "event_types": "insurance",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    events = [e for e in response.json()["events"] if e["id"] == f"insurance-{policy.id}"]
    assert len(events) == 1, "one event per policy, not one per covered vehicle"
    assert "Ram" in events[0]["description"] and "Mirage" in events[0]["description"]

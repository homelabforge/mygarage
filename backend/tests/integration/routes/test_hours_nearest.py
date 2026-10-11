"""`GET /hours/nearest?date=`: the hours reading closest to a day, for the tire dialogs (#217).

Declared above `/{record_id}`, or FastAPI reads "nearest" as a record id and
answers 422; the first test notices if it moves.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.models.vehicle import Vehicle


@pytest_asyncio.fixture
async def vin(db_session, test_user):
    made = f"HNR{uuid.uuid4().hex[:14].upper()}"
    db_session.add(
        Vehicle(
            vin=made,
            user_id=test_user["id"],
            nickname="Nearest hours",
            vehicle_type="ATV",
            year=2020,
            make="Yamaha",
            model="Grizzly",
            usage_unit="hours",
        )
    )
    await db_session.commit()
    yield made
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == made))
    await db_session.commit()


async def _seed(client, headers, vin, *rows):
    for day, hours in rows:
        made = await client.post(
            f"/api/vehicles/{vin}/hours",
            headers=headers,
            json={"vin": vin, "date": day, "engine_hours": hours},
        )
        assert made.status_code == 201, made.text


async def _nearest(client, headers, vin, day):
    return await client.get(
        f"/api/vehicles/{vin}/hours/nearest", headers=headers, params={"date": day}
    )


@pytest.mark.asyncio
class TestNearestHours:
    async def test_no_readings_is_404_not_422(self, client, auth_headers, vin):
        r = await _nearest(client, auth_headers, vin, "2026-04-10")
        assert r.status_code == 404, r.text

    async def test_nearest_before_and_after(self, client, auth_headers, vin):
        await _seed(client, auth_headers, vin, ("2026-04-01", "100.0"), ("2026-04-20", "160.0"))
        r = await _nearest(client, auth_headers, vin, "2026-04-05")
        assert r.status_code == 200, r.text
        assert r.json() == {
            "date": "2026-04-01",
            "engine_hours": "100.0",
            "source": "manual",
            "days_away": -4,
        }
        later = (await _nearest(client, auth_headers, vin, "2026-04-18")).json()
        assert (later["date"], later["days_away"]) == ("2026-04-20", 2)

    async def test_a_tie_goes_to_the_reading_on_or_before(self, client, auth_headers, vin):
        await _seed(client, auth_headers, vin, ("2026-04-01", "100.0"), ("2026-04-11", "130.0"))
        assert (await _nearest(client, auth_headers, vin, "2026-04-06")).json()[
            "date"
        ] == "2026-04-01"

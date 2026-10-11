"""Tire figures on the vehicle's axis (#217).

On an hours-only vehicle the card's distance and wear are hours, the km fields
are empty, and junk odometers from before the fix are ignored. A dual vehicle
stays on distance. Switching the vehicle flips the figures, and back.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.models.tire import TireMountPeriod, TireReading
from app.models.vehicle import Vehicle


@pytest_asyncio.fixture
async def make_vehicle(db_session, test_user):
    made: list[str] = []

    async def _make(usage_unit: str = "hours", secondary: bool = False) -> str:
        vin = f"HRF{uuid.uuid4().hex[:14].upper()}"
        db_session.add(
            Vehicle(
                vin=vin,
                user_id=test_user["id"],
                nickname="Hours figures",
                vehicle_type="ATV",
                year=2023,
                make="Honda",
                model="Pioneer",
                usage_unit=usage_unit,
                secondary_usage_enabled=secondary,
            )
        )
        await db_session.commit()
        made.append(vin)
        return vin

    yield _make
    for vin in made:
        await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
    await db_session.commit()


async def _mount(client, headers, vin, on: str, **figures) -> dict:
    made = await client.post(
        f"/api/vehicles/{vin}/tires/create-and-mount",
        headers=headers,
        json={"vin": vin, "position": "FL", "mounted_on": on, **figures},
    )
    assert made.status_code == 201, made.text
    return made.json()


async def _read(client, headers, vin, tire_id, on: str, tread: str, **figures) -> None:
    made = await client.post(
        f"/api/vehicles/{vin}/tires/{tire_id}/readings",
        headers=headers,
        json={"recorded_at": on, "tread_depth_mm": tread, **figures},
    )
    assert made.status_code == 201, made.text


async def _list(client, headers, vin) -> dict:
    listed = await client.get(f"/api/vehicles/{vin}/tires", headers=headers)
    assert listed.status_code == 200, listed.text
    return listed.json()


@pytest.mark.asyncio
class TestTheHoursAxis:
    async def test_an_hours_tire_projects_in_hours(self, client, auth_headers, make_vehicle):
        vin = await make_vehicle("hours")
        tire = await _mount(client, auth_headers, vin, "2026-01-01", mounted_hours="90")
        await _read(client, auth_headers, vin, tire["id"], "2026-01-01", "8.0", engine_hours="100")
        await _read(client, auth_headers, vin, tire["id"], "2026-01-11", "7.0", engine_hours="150")
        listed = await _list(client, auth_headers, vin)
        assert (listed["usage_axis"], listed["tracks_distance"], listed["tracks_hours"]) == (
            "hours",
            False,
            True,
        )
        [card] = listed["tires"]
        assert card["usage_axis"] == "hours"
        assert card["wear_status"] == "projected"
        assert card["projected_usage_remaining"] == "250.0"
        assert card["projected_wear_date"] == "2026-03-02"
        assert card["distance_status"] == "complete"
        assert Decimal(card["usage_on_tire"]) == Decimal("60.0")
        assert (card["projected_km_remaining"], card["distance_km"], card["known_distance_km"]) == (
            None,
            None,
            None,
        )

    async def test_junk_odometers_on_an_hours_vehicle_are_ignored(
        self, client, auth_headers, db_session, make_vehicle
    ):
        vin = await make_vehicle("hours")
        tire = await _mount(client, auth_headers, vin, "2026-01-01")
        # Before the fix: the hour meter typed as odometers, contradicting each other on distance.
        period = await db_session.get(TireMountPeriod, tire["mount_periods"][0]["id"])
        period.mounted_odometer_km = Decimal("170.00")
        db_session.add(
            TireReading(
                tire_id=tire["id"],
                vin=vin,
                position="FL",
                recorded_at=date(2026, 2, 1),
                odometer_km=Decimal("120.00"),
                tread_depth_mm=Decimal("7.00"),
            )
        )
        await db_session.commit()
        [card] = (await _list(client, auth_headers, vin))["tires"]
        assert card["usage_axis"] == "hours"
        assert card["history_faults"] == []
        assert card["distance_status"] == "nothing_bounded"
        assert card["distance_km"] is None


@pytest.mark.asyncio
class TestTheDualVehicle:
    async def test_it_runs_on_distance(self, client, auth_headers, make_vehicle):
        vin = await make_vehicle("hours", secondary=True)
        await _mount(
            client, auth_headers, vin, "2026-01-01", mounted_odometer_km="1000", mounted_hours="50"
        )
        odometer = await client.post(
            f"/api/vehicles/{vin}/odometer",
            headers=auth_headers,
            json={"vin": vin, "date": "2026-03-01", "odometer_km": "3000"},
        )
        assert odometer.status_code == 201, odometer.text
        listed = await _list(client, auth_headers, vin)
        assert (listed["usage_axis"], listed["tracks_distance"], listed["tracks_hours"]) == (
            "distance",
            True,
            True,
        )
        [card] = listed["tires"]
        assert card["usage_axis"] == "distance"
        assert Decimal(card["usage_on_tire"]) == Decimal("2000")
        assert card["usage_on_tire"] == card["distance_km"]

    async def test_a_unit_switch_flips_the_figures_and_back(
        self, client, auth_headers, make_vehicle
    ):
        vin = await make_vehicle("distance", secondary=True)
        await _mount(
            client, auth_headers, vin, "2026-01-01", mounted_odometer_km="1000", mounted_hours="50"
        )
        odometer = await client.post(
            f"/api/vehicles/{vin}/odometer",
            headers=auth_headers,
            json={"vin": vin, "date": "2026-03-01", "odometer_km": "3000"},
        )
        assert odometer.status_code == 201, odometer.text
        hours = await client.post(
            f"/api/vehicles/{vin}/hours",
            headers=auth_headers,
            json={"vin": vin, "date": "2026-03-01", "engine_hours": "80"},
        )
        assert hours.status_code == 201, hours.text

        async def card() -> dict:
            return (await _list(client, auth_headers, vin))["tires"][0]

        async def switch(usage_unit: str, secondary: bool) -> None:
            put = await client.put(
                f"/api/vehicles/{vin}",
                headers=auth_headers,
                json={"usage_unit": usage_unit, "secondary_usage_enabled": secondary},
            )
            assert put.status_code == 200, put.text

        assert Decimal((await card())["usage_on_tire"]) == Decimal("2000")
        await switch("hours", False)
        flipped = await card()
        assert flipped["usage_axis"] == "hours"
        assert Decimal(flipped["usage_on_tire"]) == Decimal("30.0")
        assert flipped["distance_km"] is None
        await switch("distance", True)
        assert Decimal((await card())["usage_on_tire"]) == Decimal("2000")


@pytest.mark.asyncio
class TestAnalytics:
    async def test_it_reads_the_axis(self, client, auth_headers, make_vehicle):
        vin = await make_vehicle("hours")
        tire = await _mount(client, auth_headers, vin, "2026-01-01")
        empty = await client.get(f"/api/analytics/vehicles/{vin}/tires", headers=auth_headers)
        assert empty.status_code == 200, empty.text
        assert (empty.json()["usage_axis"], empty.json()["has_usage_record"]) == ("hours", False)
        await _read(client, auth_headers, vin, tire["id"], "2026-01-02", "8.0", engine_hours="100")
        await _read(client, auth_headers, vin, tire["id"], "2026-01-12", "7.0", engine_hours="150")
        summary = (
            await client.get(f"/api/analytics/vehicles/{vin}/tires", headers=auth_headers)
        ).json()
        assert summary["has_usage_record"] is True
        # Both readings carry the hour meter, so nothing is missing on this axis.
        assert summary["readiness"]["needs_reading_odometer"] == 0
        assert summary["readiness"]["can_trend"] == 1

"""The scale a fill-up's octane was read on, RON or AKI (B4, migration 151).

The scale travels with its number: through the API (an unrelated edit keeps
the stored pair), and through the CSV and JSON exports into another vehicle.
It is part of the JSON duplicate key, so two fill-ups that differ only in
scale are two fill-ups.
"""

from __future__ import annotations

import json
import uuid
from io import BytesIO
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.models.fuel import FuelRecord
from app.models.vehicle import Vehicle

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

PREFIX = "MOCT"


@pytest_asyncio.fixture
async def two_vehicles(client: AsyncClient, auth_headers, db_session):
    vins: list[str] = []
    for n in range(2):
        vin = (PREFIX + uuid.uuid4().hex.upper())[:17]
        vin = vin.replace("O", "P").replace("I", "J").replace("Q", "R")
        r = await client.post(
            "/api/vehicles",
            headers=auth_headers,
            json={
                "vin": vin,
                "nickname": f"octane-{n}",
                "vehicle_type": "Car",
                "fuel_type": "gasoline",
            },
        )
        assert r.status_code == 201, r.text
        vins.append(vin)
    yield vins
    await db_session.rollback()
    await db_session.execute(delete(FuelRecord).where(FuelRecord.vin.in_(vins)))
    await db_session.execute(delete(Vehicle).where(Vehicle.vin.in_(vins)))
    await db_session.commit()


async def _create(client: AsyncClient, headers: dict, vin: str, **extra: Any):
    payload = {
        "vin": vin,
        "date": "2026-05-01",
        "liters": 40.0,
        "cost": 70.00,
        "odometer_km": 10_000,
        "is_full_tank": True,
        **extra,
    }
    return await client.post(f"/api/vehicles/{vin}/fuel", headers=headers, json=payload)


async def _records(client: AsyncClient, headers: dict, vin: str) -> list[dict[str, Any]]:
    r = await client.get(f"/api/vehicles/{vin}/fuel", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["records"]


class TestApi:
    async def test_create_stores_the_pair_case_insensitively(
        self, client, auth_headers, two_vehicles
    ):
        vin = two_vehicles[0]
        r = await _create(client, auth_headers, vin, octane=95, octane_scale="ron")
        assert r.status_code == 201, r.text
        assert (r.json()["octane"], r.json()["octane_scale"]) == (95, "RON")

    async def test_an_unknown_scale_is_422(self, client, auth_headers, two_vehicles):
        r = await _create(client, auth_headers, two_vehicles[0], octane=95, octane_scale="MON")
        assert r.status_code == 422, r.text

    async def test_a_scale_without_an_octane_is_not_stored(
        self, client, auth_headers, two_vehicles
    ):
        r = await _create(client, auth_headers, two_vehicles[0], octane_scale="RON")
        assert r.status_code == 201, r.text
        assert r.json()["octane_scale"] is None

    async def test_an_unrelated_edit_keeps_the_pair(self, client, auth_headers, two_vehicles):
        vin = two_vehicles[0]
        created = (await _create(client, auth_headers, vin, octane=91, octane_scale="AKI")).json()
        r = await client.put(
            f"/api/vehicles/{vin}/fuel/{created['id']}",
            headers=auth_headers,
            json={"notes": "after moving to France"},
        )
        assert r.status_code == 200, r.text
        assert (r.json()["octane"], r.json()["octane_scale"]) == (91, "AKI")

    async def test_a_legacy_null_stays_null_on_edit(self, client, auth_headers, two_vehicles):
        vin = two_vehicles[0]
        created = (await _create(client, auth_headers, vin, octane=95)).json()
        assert created["octane_scale"] is None
        r = await client.put(
            f"/api/vehicles/{vin}/fuel/{created['id']}",
            headers=auth_headers,
            json={"notes": "touched"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["octane_scale"] is None

    async def test_clearing_the_octane_clears_its_scale(self, client, auth_headers, two_vehicles):
        vin = two_vehicles[0]
        created = (await _create(client, auth_headers, vin, octane=98, octane_scale="RON")).json()
        r = await client.put(
            f"/api/vehicles/{vin}/fuel/{created['id']}",
            headers=auth_headers,
            json={"octane": None},
        )
        assert r.status_code == 200, r.text
        assert (r.json()["octane"], r.json()["octane_scale"]) == (None, None)


class TestRoundTrip:
    async def test_csv_into_another_vehicle(self, client, auth_headers, two_vehicles):
        source, target = two_vehicles
        await _create(client, auth_headers, source, octane=95, octane_scale="RON")
        await _create(
            client, auth_headers, source, octane=91, octane_scale="AKI", odometer_km=10_500
        )
        await _create(client, auth_headers, source, octane=89, odometer_km=11_000)

        r = await client.get(f"/api/export/vehicles/{source}/fuel/csv", headers=auth_headers)
        assert r.status_code == 200, r.text
        header = r.text.splitlines()[0].split(",")
        assert header.index("Octane Scale") == header.index("Octane") + 1

        r = await client.post(
            f"/api/import/vehicles/{target}/fuel/csv",
            headers=auth_headers,
            files={"file": ("fuel.csv", BytesIO(r.text.encode()), "text/csv")},
        )
        assert r.status_code == 200, r.text
        assert r.json()["error_count"] == 0, r.json()
        pairs = sorted(
            (x["octane"], x["octane_scale"]) for x in await _records(client, auth_headers, target)
        )
        assert pairs == [(89, None), (91, "AKI"), (95, "RON")]

    async def test_csv_bad_scale_fails_its_row_alone(self, client, auth_headers, two_vehicles):
        vin = two_vehicles[1]
        content = (
            "Date,Odometer (km),Liters,Total Cost,Full Tank,Octane,Octane Scale\n"
            "2026-05-07,20500,41.0,61.50,True,95,MON\n"
            "2026-05-08,20600,41.0,61.50,True,95,ron\n"
        )
        r = await client.post(
            f"/api/import/vehicles/{vin}/fuel/csv",
            headers=auth_headers,
            files={"file": ("fuel.csv", BytesIO(content.encode()), "text/csv")},
        )
        assert r.status_code == 200, r.text
        assert (r.json()["error_count"], r.json()["success_count"]) == (1, 1)
        records = await _records(client, auth_headers, vin)
        assert [x["octane_scale"] for x in records] == ["RON"]

    async def test_json_into_another_vehicle(self, client, auth_headers, two_vehicles):
        source, target = two_vehicles
        await _create(client, auth_headers, source, octane=98, octane_scale="RON")
        await _create(client, auth_headers, source, octane=93, odometer_km=10_500)

        backup = (
            await client.get(f"/api/export/vehicles/{source}/json", headers=auth_headers)
        ).json()
        assert sorted((x["octane"], x["octane_scale"]) for x in backup["fuel_records"]) == [
            (93, None),
            (98, "RON"),
        ]

        r = await client.post(
            f"/api/import/vehicles/{target}/json",
            headers=auth_headers,
            files={"file": ("b.json", BytesIO(json.dumps(backup).encode()), "application/json")},
        )
        assert r.status_code == 200, r.text
        pairs = sorted(
            (x["octane"], x["octane_scale"]) for x in await _records(client, auth_headers, target)
        )
        assert pairs == [(93, None), (98, "RON")]

    async def test_json_rows_differing_only_in_scale_are_not_duplicates(
        self, client, auth_headers, two_vehicles, db_session
    ):
        vin = two_vehicles[1]
        row = {"date": "2026-06-01", "odometer_km": 30000.0, "liters": 40.0, "octane": 95}
        await _create(
            client,
            auth_headers,
            vin,
            date="2026-06-01",
            odometer_km=30_000,
            octane=95,
            octane_scale="RON",
            cost=None,
        )
        backup = {
            "export_version": "9",
            "units": "metric",
            "fuel_records": [
                row | {"octane_scale": "RON"},  # the stored one: a duplicate
                row | {"octane_scale": "AKI"},  # same number, other scale: new
            ],
        }
        r = await client.post(
            f"/api/import/vehicles/{vin}/json",
            headers=auth_headers,
            files={"file": ("b.json", BytesIO(json.dumps(backup).encode()), "application/json")},
        )
        assert r.status_code == 200, r.text
        scales = sorted(
            row[0]
            for row in (
                await db_session.execute(
                    select(FuelRecord.octane_scale).where(FuelRecord.vin == vin)
                )
            ).all()
        )
        assert scales == ["AKI", "RON"]

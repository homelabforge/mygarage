"""Clearing a source record's odometer removes the reading it synced.

Until the edit forms posted null for a cleared field, nothing could clear a
source's odometer, and `sync_odometer_from_record` simply skips a None. Once
clearing worked, the synced row stayed behind: a typo'd 724,200 km visit,
cleared on edit, left 724,200 as the vehicle's highest reading for reminders
to project from. The hours track has always deleted its row on a clear.
"""

import pytest
from httpx import AsyncClient

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.own_vehicle(vehicle_type="Truck", make="Ram", model="2500", fuel_type="diesel"),
]


async def _odometer_rows(client: AsyncClient, headers: dict, vin: str) -> list[dict]:
    r = await client.get(f"/api/vehicles/{vin}/odometer", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["records"]


def _marked(rows: list[dict], source_type: str, source_id: int) -> list[dict]:
    marker = f"[AUTO-SYNC from {source_type} #{source_id}]"
    return [r for r in rows if r.get("notes") == marker]


async def _visit(
    client: AsyncClient, headers: dict, vin: str, *, on: str, odometer_km: float
) -> dict:
    r = await client.post(
        f"/api/vehicles/{vin}/service-visits",
        json={"date": on, "odometer_km": odometer_km, "line_items": [{"description": "Oil"}]},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


class TestServiceVisitClear:
    async def test_clearing_the_odometer_removes_the_synced_reading(
        self, client: AsyncClient, auth_headers, own_vehicle
    ):
        vin = own_vehicle.vin
        visit = await _visit(client, auth_headers, vin, on="2031-08-10", odometer_km=724200)
        rows = await _odometer_rows(client, auth_headers, vin)
        assert len(_marked(rows, "service_visit", visit["id"])) == 1

        r = await client.put(
            f"/api/vehicles/{vin}/service-visits/{visit['id']}",
            json={"odometer_km": None},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        assert r.json()["odometer_km"] is None
        rows = await _odometer_rows(client, auth_headers, vin)
        assert _marked(rows, "service_visit", visit["id"]) == []

    async def test_a_manual_reading_on_the_same_day_survives(
        self, client: AsyncClient, auth_headers, own_vehicle
    ):
        """The visit syncs first, so there IS a row to delete; the manual one
        added after it on the same day must be the one that stays."""
        vin = own_vehicle.vin
        visit = await _visit(client, auth_headers, vin, on="2031-08-11", odometer_km=724100)
        r = await client.post(
            f"/api/vehicles/{vin}/odometer",
            json={"vin": vin, "date": "2031-08-11", "odometer_km": 724000, "notes": "dash photo"},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        manual_id = r.json()["id"]
        rows = await _odometer_rows(client, auth_headers, vin)
        assert len(_marked(rows, "service_visit", visit["id"])) == 1

        r = await client.put(
            f"/api/vehicles/{vin}/service-visits/{visit['id']}",
            json={"odometer_km": None},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        rows = await _odometer_rows(client, auth_headers, vin)
        assert _marked(rows, "service_visit", visit["id"]) == []
        assert any(row["id"] == manual_id for row in rows)

    async def test_an_edit_to_zero_removes_the_synced_reading(
        self, client: AsyncClient, auth_headers, own_vehicle
    ):
        """A create with 0 never syncs, so an edit to 0 must not keep the old reading."""
        vin = own_vehicle.vin
        visit = await _visit(client, auth_headers, vin, on="2031-08-13", odometer_km=724500)

        r = await client.put(
            f"/api/vehicles/{vin}/service-visits/{visit['id']}",
            json={"odometer_km": 0},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        rows = await _odometer_rows(client, auth_headers, vin)
        assert _marked(rows, "service_visit", visit["id"]) == []

    async def test_an_edit_that_leaves_the_odometer_alone_keeps_the_reading(
        self, client: AsyncClient, auth_headers, own_vehicle
    ):
        vin = own_vehicle.vin
        visit = await _visit(client, auth_headers, vin, on="2031-08-12", odometer_km=724300)

        r = await client.put(
            f"/api/vehicles/{vin}/service-visits/{visit['id']}",
            json={"notes": "edited"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        rows = _marked(
            await _odometer_rows(client, auth_headers, vin), "service_visit", visit["id"]
        )
        assert len(rows) == 1 and float(rows[0]["odometer_km"]) == 724300


class TestFuelClear:
    async def test_clearing_the_odometer_removes_the_synced_reading(
        self, client: AsyncClient, auth_headers, own_vehicle
    ):
        vin = own_vehicle.vin
        r = await client.post(
            f"/api/vehicles/{vin}/fuel",
            json={
                "vin": vin,
                "date": "2031-09-10",
                "liters": 40.0,
                "cost": 45.00,
                "odometer_km": 725000,
                # Engine hours stay as the reading, so the fill-up is still
                # one create would accept once the odometer is cleared.
                "engine_hours": 310.5,
                "is_full_tank": True,
            },
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        record = r.json()
        assert (
            len(_marked(await _odometer_rows(client, auth_headers, vin), "fuel", record["id"])) == 1
        )

        r = await client.put(
            f"/api/vehicles/{vin}/fuel/{record['id']}",
            json={"odometer_km": None},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        assert _marked(await _odometer_rows(client, auth_headers, vin), "fuel", record["id"]) == []


class TestDefClear:
    async def test_clearing_the_odometer_removes_the_synced_reading(
        self, client: AsyncClient, auth_headers, own_vehicle
    ):
        vin = own_vehicle.vin
        r = await client.post(
            f"/api/vehicles/{vin}/def",
            json={"vin": vin, "date": "2031-09-11", "odometer_km": 725100, "liters": 9.5},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        record = r.json()
        assert (
            len(_marked(await _odometer_rows(client, auth_headers, vin), "def", record["id"])) == 1
        )

        r = await client.put(
            f"/api/vehicles/{vin}/def/{record['id']}",
            json={"odometer_km": None},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        assert _marked(await _odometer_rows(client, auth_headers, vin), "def", record["id"]) == []


class TestEditToZero:
    """A create with 0 never syncs, so an edit to 0 must not keep the old reading."""

    async def test_a_fill_up_edited_to_zero(self, client: AsyncClient, auth_headers, own_vehicle):
        vin = own_vehicle.vin
        r = await client.post(
            f"/api/vehicles/{vin}/fuel",
            json={"vin": vin, "date": "2031-09-12", "liters": 40.0, "odometer_km": 725200},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        record = r.json()

        r = await client.put(
            f"/api/vehicles/{vin}/fuel/{record['id']}",
            json={"odometer_km": 0},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text

        assert _marked(await _odometer_rows(client, auth_headers, vin), "fuel", record["id"]) == []

    async def test_a_def_record_edited_to_zero(
        self, client: AsyncClient, auth_headers, own_vehicle
    ):
        vin = own_vehicle.vin
        r = await client.post(
            f"/api/vehicles/{vin}/def",
            json={"vin": vin, "date": "2031-09-13", "odometer_km": 725300, "liters": 9.5},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        record = r.json()

        r = await client.put(
            f"/api/vehicles/{vin}/def/{record['id']}", json={"odometer_km": 0}, headers=auth_headers
        )
        assert r.status_code == 200, r.text

        assert _marked(await _odometer_rows(client, auth_headers, vin), "def", record["id"]) == []

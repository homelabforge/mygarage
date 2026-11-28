"""
Integration tests for DEF (Diesel Exhaust Fluid) record routes.

Tests DEF record CRUD operations and analytics.
"""

import pytest
from httpx import AsyncClient

from app.utils.odometer_sync import auto_sync_marker


@pytest.mark.integration
@pytest.mark.def_records
@pytest.mark.asyncio
class TestDEFRecordRoutes:
    """Test DEF record API endpoints."""

    async def test_list_def_records_empty(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test listing DEF records when none exist."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/def",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "records" in data
        assert "total" in data
        assert isinstance(data["records"], list)

    async def test_create_def_record(
        self, client: AsyncClient, auth_headers, test_vehicle, sample_def_payload
    ):
        """Test creating a new DEF record."""
        payload = {**sample_def_payload, "vin": test_vehicle["vin"]}
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/def",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert float(data["liters"]) == pytest.approx(payload["liters"], abs=0.01)
        assert float(data["cost"]) == payload["cost"]
        assert float(data["fill_level"]) == payload["fill_level"]
        assert data["source"] == payload["source"]
        assert data["brand"] == payload["brand"]

    async def test_create_def_record_minimal(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating a DEF record with only required fields."""
        payload = {
            "vin": test_vehicle["vin"],
            "date": "2024-06-01",
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/def",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["date"] == "2024-06-01"

    async def test_get_def_record_by_id(
        self, client: AsyncClient, auth_headers, test_vehicle, sample_def_payload
    ):
        """Test retrieving a specific DEF record."""
        payload = {**sample_def_payload, "vin": test_vehicle["vin"]}
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/def",
            json=payload,
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        record = create_response.json()

        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/def/{record['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == record["id"]
        assert float(data["liters"]) == pytest.approx(payload["liters"], abs=0.01)

    async def test_get_def_record_not_found(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test retrieving a non-existent DEF record."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/def/99999",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_update_def_record(
        self, client: AsyncClient, auth_headers, test_vehicle, sample_def_payload
    ):
        """Test updating a DEF record."""
        payload = {**sample_def_payload, "vin": test_vehicle["vin"]}
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/def",
            json=payload,
            headers=auth_headers,
        )
        record = create_response.json()

        update_data = {
            "cost": 25.00,
            "notes": "Updated cost",
            "fill_level": 0.75,
        }

        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/def/{record['id']}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert float(data["cost"]) == 25.00
        assert data["notes"] == "Updated cost"
        assert float(data["fill_level"]) == 0.75

    async def test_delete_def_record(
        self, client: AsyncClient, auth_headers, test_vehicle, sample_def_payload
    ):
        """Test deleting a DEF record."""
        payload = {**sample_def_payload, "vin": test_vehicle["vin"]}
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/def",
            json=payload,
            headers=auth_headers,
        )
        record = create_response.json()

        response = await client.delete(
            f"/api/vehicles/{test_vehicle['vin']}/def/{record['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's gone
        get_response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/def/{record['id']}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_delete_def_record_not_found(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test deleting a non-existent DEF record."""
        response = await client.delete(
            f"/api/vehicles/{test_vehicle['vin']}/def/99999",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_def_record_invalid_vehicle(self, client: AsyncClient, auth_headers):
        """Test creating a DEF record for a non-existent vehicle."""
        fake_vin = "ZZZZZZZZZZZZZZ999"
        response = await client.post(
            f"/api/vehicles/{fake_vin}/def",
            json={
                "vin": fake_vin,
                "date": "2024-01-15",
                "liters": 9.464,
            },
            headers=auth_headers,
        )

        assert response.status_code in (403, 404)

    async def test_def_record_fill_level_validation(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that fill_level is validated between 0 and 1."""
        # fill_level > 1 should fail
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/def",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-01-15",
                "fill_level": 1.5,
            },
            headers=auth_headers,
        )

        assert response.status_code == 422

    async def test_def_unauthenticated(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated requests are rejected."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/def",
        )

        assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.def_records
@pytest.mark.asyncio
class TestDEFAnalytics:
    """Test DEF analytics endpoint."""

    async def test_analytics_returns_valid_response(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test analytics endpoint returns valid structure."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/def/analytics",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "record_count" in data
        assert "data_confidence" in data
        assert data["data_confidence"] in ("high", "low", "insufficient")
        assert isinstance(data["record_count"], int)

    async def test_analytics_with_records(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test analytics with multiple DEF records."""
        # Create several records with mileage data
        records = [
            {
                "vin": test_vehicle["vin"],
                "date": "2024-01-01",
                "odometer_km": 16093.40,
                "liters": 9.464,
                "cost": 15.00,
                "fill_level": 1.0,
            },
            {
                "vin": test_vehicle["vin"],
                "date": "2024-02-01",
                "odometer_km": 19312.08,
                "liters": 9.464,
                "cost": 16.00,
                "fill_level": 0.75,
            },
            {
                "vin": test_vehicle["vin"],
                "date": "2024-03-01",
                "odometer_km": 22530.76,
                "liters": 9.464,
                "cost": 14.50,
                "fill_level": 0.50,
            },
        ]

        for record in records:
            resp = await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/def",
                json=record,
                headers=auth_headers,
            )
            assert resp.status_code == 201

        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/def/analytics",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["record_count"] >= 3
        assert data["total_liters"] is not None
        assert data["total_cost"] is not None


async def _def_rows(client: AsyncClient, headers: dict, vin: str, def_id: int) -> list[dict]:
    """The odometer rows a DEF record synced."""
    listed = await client.get(f"/api/vehicles/{vin}/odometer", headers=headers)
    assert listed.status_code == 200, listed.text
    marker = auto_sync_marker("def", def_id)
    return [r for r in listed.json()["records"] if r["notes"] == marker]


@pytest.mark.integration
@pytest.mark.def_records
@pytest.mark.asyncio
@pytest.mark.own_vehicle(fuel_type="diesel")
class TestDeletingDEFTakesItsReading:
    """A deleted DEF record takes the odometer reading it synced with it."""

    async def test_deleting_the_record_removes_its_reading(
        self, client: AsyncClient, auth_headers, own_vehicle, sample_def_payload
    ):
        vin = own_vehicle.vin
        made = await client.post(
            f"/api/vehicles/{vin}/def",
            json={**sample_def_payload, "vin": vin},
            headers=auth_headers,
        )
        assert made.status_code == 201, made.text
        def_id = made.json()["id"]
        assert len(await _def_rows(client, auth_headers, vin, def_id)) == 1

        gone = await client.delete(f"/api/vehicles/{vin}/def/{def_id}", headers=auth_headers)
        assert gone.status_code == 204, gone.text
        assert await _def_rows(client, auth_headers, vin, def_id) == []

    async def test_deleting_the_fill_up_removes_its_edited_def_records_reading(
        self, client: AsyncClient, auth_headers, own_vehicle
    ):
        """A DEF record a fill-up wrote syncs its own reading once edited, and goes with the fill-up."""
        vin = own_vehicle.vin
        fuel = await client.post(
            f"/api/vehicles/{vin}/fuel",
            json={
                "vin": vin,
                "date": "2026-08-06",
                "odometer_km": 50000,
                "liters": 45.0,
                "def_fill_level": 0.75,
            },
            headers=auth_headers,
        )
        assert fuel.status_code == 201, fuel.text
        listed = await client.get(f"/api/vehicles/{vin}/def", headers=auth_headers)
        assert listed.status_code == 200, listed.text
        [def_record] = listed.json()["records"]
        edited = await client.put(
            f"/api/vehicles/{vin}/def/{def_record['id']}",
            json={"odometer_km": 50010},
            headers=auth_headers,
        )
        assert edited.status_code == 200, edited.text
        assert len(await _def_rows(client, auth_headers, vin, def_record["id"])) == 1

        gone = await client.delete(
            f"/api/vehicles/{vin}/fuel/{fuel.json()['id']}", headers=auth_headers
        )
        assert gone.status_code == 204, gone.text
        assert await _def_rows(client, auth_headers, vin, def_record["id"]) == []


async def _readings_on(client: AsyncClient, headers: dict, vin: str, day: str) -> list[dict]:
    """Every odometer reading on one date."""
    listed = await client.get(f"/api/vehicles/{vin}/odometer", headers=headers)
    assert listed.status_code == 200, listed.text
    return [r for r in listed.json()["records"] if r["date"] == day]


async def _fill_up_with_def(client: AsyncClient, headers: dict, vin: str, day: str) -> dict:
    """A fill-up at 50000 km that logged a DEF level, so it wrote a DEF record too."""
    fuel = await client.post(
        f"/api/vehicles/{vin}/fuel",
        json={
            "vin": vin,
            "date": day,
            "odometer_km": 50000,
            "liters": 45.0,
            "def_fill_level": 0.75,
        },
        headers=headers,
    )
    assert fuel.status_code == 201, fuel.text
    return fuel.json()


@pytest.mark.integration
@pytest.mark.def_records
@pytest.mark.asyncio
@pytest.mark.own_vehicle(fuel_type="diesel")
class TestDEFNeverTakesAnotherReading:
    """A DEF record only adds a reading when the day doesn't already read that high."""

    async def test_deleting_a_same_day_def_purchase_keeps_the_fill_ups_reading(
        self, client: AsyncClient, auth_headers, own_vehicle
    ):
        vin = own_vehicle.vin
        fuel = await client.post(
            f"/api/vehicles/{vin}/fuel",
            json={"vin": vin, "date": "2026-08-06", "odometer_km": 50000, "liters": 45.0},
            headers=auth_headers,
        )
        assert fuel.status_code == 201, fuel.text
        made = await client.post(
            f"/api/vehicles/{vin}/def",
            json={"vin": vin, "date": "2026-08-06", "odometer_km": 50000, "liters": 9.5},
            headers=auth_headers,
        )
        assert made.status_code == 201, made.text

        gone = await client.delete(
            f"/api/vehicles/{vin}/def/{made.json()['id']}", headers=auth_headers
        )
        assert gone.status_code == 204, gone.text
        readings = await _readings_on(client, auth_headers, vin, "2026-08-06")
        assert [(r["notes"], float(r["odometer_km"])) for r in readings] == [
            (auto_sync_marker("fuel", fuel.json()["id"]), 50000.0)
        ]

    async def test_editing_a_fill_ups_def_record_adds_no_second_reading(
        self, client: AsyncClient, auth_headers, own_vehicle
    ):
        vin = own_vehicle.vin
        await _fill_up_with_def(client, auth_headers, vin, "2026-08-06")
        listed = await client.get(f"/api/vehicles/{vin}/def", headers=auth_headers)
        assert listed.status_code == 200, listed.text
        [def_record] = listed.json()["records"]

        edited = await client.put(
            f"/api/vehicles/{vin}/def/{def_record['id']}",
            json={"fill_level": 0.8},
            headers=auth_headers,
        )
        assert edited.status_code == 200, edited.text
        assert len(await _readings_on(client, auth_headers, vin, "2026-08-06")) == 1


@pytest.mark.integration
@pytest.mark.def_records
@pytest.mark.asyncio
@pytest.mark.own_vehicle(fuel_type="diesel")
class TestClearingTheDEFLevelTakesItsReading:
    """Clearing a fill-up's DEF level drops its DEF record and the reading that record synced."""

    async def test_clearing_the_level_removes_the_edited_def_records_reading(
        self, client: AsyncClient, auth_headers, own_vehicle
    ):
        vin = own_vehicle.vin
        fuel = await _fill_up_with_def(client, auth_headers, vin, "2026-08-06")
        listed = await client.get(f"/api/vehicles/{vin}/def", headers=auth_headers)
        assert listed.status_code == 200, listed.text
        [def_record] = listed.json()["records"]
        edited = await client.put(
            f"/api/vehicles/{vin}/def/{def_record['id']}",
            json={"odometer_km": 50010},
            headers=auth_headers,
        )
        assert edited.status_code == 200, edited.text
        assert len(await _def_rows(client, auth_headers, vin, def_record["id"])) == 1

        cleared = await client.put(
            f"/api/vehicles/{vin}/fuel/{fuel['id']}",
            json={"def_fill_level": None},
            headers=auth_headers,
        )
        assert cleared.status_code == 200, cleared.text
        assert (await client.get(f"/api/vehicles/{vin}/def", headers=auth_headers)).json()[
            "records"
        ] == []
        assert await _def_rows(client, auth_headers, vin, def_record["id"]) == []

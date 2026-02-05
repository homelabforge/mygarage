"""
Integration tests for odometer record routes.

Tests odometer record CRUD operations and mileage tracking.
"""

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestOdometerRecordRoutes:
    """Test odometer record API endpoints."""

    async def test_list_odometer_records(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test listing odometer records for a vehicle."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/odometer",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "records" in data
        assert "total" in data
        assert "latest_mileage" in data
        assert isinstance(data["records"], list)

    async def test_get_odometer_record_by_id(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test retrieving a specific odometer record."""
        # First create an odometer record
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/odometer",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-01-15",
                "mileage": 50000,
                "notes": "Monthly reading",
            },
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        record = create_response.json()

        # Get the odometer record
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/odometer/{record['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == record["id"]
        assert data["mileage"] == 50000
        assert data["notes"] == "Monthly reading"

    async def test_create_odometer_record(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating a new odometer record."""
        payload = {
            "vin": test_vehicle["vin"],
            "date": datetime.now().date().isoformat(),
            "mileage": 55000,
            "notes": "Test odometer reading",
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/odometer",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["mileage"] == payload["mileage"]
        assert data["notes"] == payload["notes"]
        assert "id" in data
        assert "created_at" in data

    async def test_update_odometer_record(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test updating an odometer record."""
        # Create an odometer record
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/odometer",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-02-01",
                "mileage": 52000,
                "notes": "Original reading",
            },
            headers=auth_headers,
        )
        record = create_response.json()

        # Update the record
        update_data = {
            "mileage": 52100,
            "notes": "Corrected reading",
        }

        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/odometer/{record['id']}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["mileage"] == 52100
        assert data["notes"] == "Corrected reading"

    async def test_delete_odometer_record(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test deleting an odometer record."""
        # Create an odometer record
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/odometer",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-02-15",
                "mileage": 53000,
            },
            headers=auth_headers,
        )
        record = create_response.json()

        # Delete the record
        response = await client.delete(
            f"/api/vehicles/{test_vehicle['vin']}/odometer/{record['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/odometer/{record['id']}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_odometer_record_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot access odometer records."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}/odometer")

        assert response.status_code == 401

    async def test_create_odometer_record_validation(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that invalid odometer records are rejected."""
        invalid_payload = {
            "vin": test_vehicle["vin"],
            "date": "2024-01-15",
            "mileage": -1000,  # Negative mileage should fail
        }

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/odometer",
            json=invalid_payload,
            headers=auth_headers,
        )

        assert response.status_code == 422  # Validation error

    async def test_odometer_record_pagination(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test odometer record pagination."""
        # Create multiple odometer records
        for i in range(10):
            await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/odometer",
                json={
                    "vin": test_vehicle["vin"],
                    "date": (datetime.now() - timedelta(days=i * 30)).date().isoformat(),
                    "mileage": 60000 + (i * 1000),
                },
                headers=auth_headers,
            )

        # Test pagination with limit
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/odometer?skip=0&limit=5",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["records"]) <= 5

    async def test_odometer_record_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test odometer record with non-existent vehicle."""
        response = await client.get(
            "/api/vehicles/NONEXISTENT12345VN/odometer",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_odometer_latest_mileage_tracking(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that latest_mileage is correctly tracked."""
        # Use far-future dates to ensure this is the latest record
        # Create multiple odometer records with different dates
        records = [
            {"date": "2030-01-01", "mileage": 140000},
            {"date": "2030-02-01", "mileage": 142000},
            {"date": "2030-03-01", "mileage": 144000},  # Latest by date
        ]

        for record in records:
            await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/odometer",
                json={
                    "vin": test_vehicle["vin"],
                    "date": record["date"],
                    "mileage": record["mileage"],
                },
                headers=auth_headers,
            )

        # Get list and check latest_mileage
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/odometer",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Latest mileage should be from the most recent date
        assert data["latest_mileage"] == 144000

    async def test_odometer_record_ordering(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test that odometer records are ordered by date descending."""
        # Create records out of order
        dates_and_mileages = [
            ("2024-02-01", 42000),
            ("2024-01-01", 40000),
            ("2024-03-01", 44000),
        ]

        for date, mileage in dates_and_mileages:
            await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/odometer",
                json={
                    "vin": test_vehicle["vin"],
                    "date": date,
                    "mileage": mileage,
                },
                headers=auth_headers,
            )

        # Get list
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/odometer",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        records = data["records"]

        # Records should be ordered by date descending
        if len(records) >= 2:
            for i in range(len(records) - 1):
                assert records[i]["date"] >= records[i + 1]["date"]

    async def test_create_odometer_record_with_notes(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test creating odometer record with optional notes."""
        # Without notes
        response_no_notes = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/odometer",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-04-01",
                "mileage": 70000,
            },
            headers=auth_headers,
        )
        assert response_no_notes.status_code == 201
        data_no_notes = response_no_notes.json()
        assert data_no_notes["notes"] is None

        # With notes
        response_with_notes = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/odometer",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-04-15",
                "mileage": 71000,
                "notes": "Annual inspection reading",
            },
            headers=auth_headers,
        )
        assert response_with_notes.status_code == 201
        data_with_notes = response_with_notes.json()
        assert data_with_notes["notes"] == "Annual inspection reading"

    async def test_update_odometer_record_partial(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test partial update of odometer record (only some fields)."""
        # Create an odometer record
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/odometer",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-05-01",
                "mileage": 75000,
                "notes": "Original notes",
            },
            headers=auth_headers,
        )
        record = create_response.json()

        # Update only notes (leave mileage unchanged)
        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/odometer/{record['id']}",
            json={"notes": "Updated notes only"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["mileage"] == 75000  # Unchanged
        assert data["notes"] == "Updated notes only"

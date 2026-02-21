"""
Integration tests for fuel record routes.

Tests fuel record CRUD operations and MPG calculations.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.fuel
@pytest.mark.asyncio
class TestFuelRecordRoutes:
    """Test fuel record API endpoints."""

    async def test_list_fuel_records(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test listing fuel records for a vehicle."""
        vehicle = test_vehicle_with_records
        response = await client.get(
            f"/api/vehicles/{vehicle['vin']}/fuel",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "records" in data
        assert "total" in data
        assert "average_mpg" in data
        assert isinstance(data["records"], list)

    async def test_get_fuel_record_by_id(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test retrieving a specific fuel record."""
        vehicle = test_vehicle_with_records

        # First create a fuel record (vin required in body)
        create_response = await client.post(
            f"/api/vehicles/{vehicle['vin']}/fuel",
            json={
                "vin": vehicle["vin"],
                "date": "2024-01-15",
                "gallons": 12.5,
                "cost": 45.00,
                "mileage": 15500,
                "is_full_tank": True,
                "price_per_unit": 3.60,
            },
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        record = create_response.json()

        # Get the fuel record
        response = await client.get(
            f"/api/vehicles/{vehicle['vin']}/fuel/{record['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == record["id"]
        # Decimal fields are serialized as strings
        assert float(data["gallons"]) == 12.5
        assert float(data["cost"]) == 45.00

    async def test_create_fuel_record(
        self, client: AsyncClient, auth_headers, test_vehicle, sample_fuel_payload
    ):
        """Test creating a new fuel record."""
        # Add vin to payload (required by API)
        payload = {**sample_fuel_payload, "vin": test_vehicle["vin"]}
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/fuel",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        # Decimal fields are serialized as strings
        assert float(data["gallons"]) == payload["gallons"]
        assert float(data["cost"]) == payload["cost"]
        assert "id" in data
        # MPG might be null for first record
        assert "mpg" in data

    async def test_update_fuel_record(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test updating a fuel record."""
        vehicle = test_vehicle_with_records

        # Create a fuel record
        create_response = await client.post(
            f"/api/vehicles/{vehicle['vin']}/fuel",
            json={
                "vin": vehicle["vin"],
                "date": "2024-01-15",
                "gallons": 12.5,
                "cost": 45.00,
                "mileage": 15500,
                "is_full_tank": True,
                "price_per_unit": 3.60,
            },
            headers=auth_headers,
        )
        record = create_response.json()

        # Update the record
        update_data = {
            "cost": 50.00,
            "notes": "Updated cost",
        }

        response = await client.put(
            f"/api/vehicles/{vehicle['vin']}/fuel/{record['id']}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert float(data["cost"]) == 50.00
        assert data["notes"] == "Updated cost"

    async def test_delete_fuel_record(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test deleting a fuel record."""
        vehicle = test_vehicle_with_records

        # Create a fuel record
        create_response = await client.post(
            f"/api/vehicles/{vehicle['vin']}/fuel",
            json={
                "vin": vehicle["vin"],
                "date": "2024-01-15",
                "gallons": 12.5,
                "cost": 45.00,
                "mileage": 15500,
                "is_full_tank": True,
                "price_per_unit": 3.60,
            },
            headers=auth_headers,
        )
        record = create_response.json()

        # Delete the record
        response = await client.delete(
            f"/api/vehicles/{vehicle['vin']}/fuel/{record['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(
            f"/api/vehicles/{vehicle['vin']}/fuel/{record['id']}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_fuel_mpg_calculation(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test that MPG is calculated correctly for consecutive full tanks."""
        vehicle = test_vehicle

        # First fill-up (baseline)
        first_response = await client.post(
            f"/api/vehicles/{vehicle['vin']}/fuel",
            json={
                "vin": vehicle["vin"],
                "date": "2024-01-01",
                "gallons": 12.0,
                "cost": 43.20,
                "mileage": 10000,
                "is_full_tank": True,
                "price_per_unit": 3.60,
            },
            headers=auth_headers,
        )
        assert first_response.status_code == 201
        first_record = first_response.json()
        # First record should have no MPG (no previous record)
        assert first_record["mpg"] is None

        # Second fill-up (should calculate MPG)
        second_response = await client.post(
            f"/api/vehicles/{vehicle['vin']}/fuel",
            json={
                "vin": vehicle["vin"],
                "date": "2024-01-15",
                "gallons": 12.0,
                "cost": 43.20,
                "mileage": 10300,  # 300 miles driven
                "is_full_tank": True,
                "price_per_unit": 3.60,
            },
            headers=auth_headers,
        )
        assert second_response.status_code == 201
        second_record = second_response.json()
        # 300 miles / 12 gallons = 25 MPG
        assert second_record["mpg"] is not None
        assert float(second_record["mpg"]) == pytest.approx(25.0, rel=0.1)

    async def test_partial_fillup_no_mpg(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test that partial fill-ups don't calculate MPG."""
        vehicle = test_vehicle

        # Full tank baseline
        await client.post(
            f"/api/vehicles/{vehicle['vin']}/fuel",
            json={
                "vin": vehicle["vin"],
                "date": "2024-01-01",
                "gallons": 12.0,
                "cost": 43.20,
                "mileage": 10000,
                "is_full_tank": True,
                "price_per_unit": 3.60,
            },
            headers=auth_headers,
        )

        # Partial fill-up
        partial_response = await client.post(
            f"/api/vehicles/{vehicle['vin']}/fuel",
            json={
                "vin": vehicle["vin"],
                "date": "2024-01-15",
                "gallons": 8.0,
                "cost": 28.80,
                "mileage": 10300,
                "is_full_tank": False,  # Partial
                "price_per_unit": 3.60,
            },
            headers=auth_headers,
        )
        assert partial_response.status_code == 201
        partial_record = partial_response.json()
        # Partial fill-ups should not have MPG
        assert partial_record["mpg"] is None

    async def test_fuel_record_unauthorized(self, client: AsyncClient, test_vehicle_with_records):
        """Test that unauthenticated users cannot access fuel records."""
        vehicle = test_vehicle_with_records
        response = await client.get(f"/api/vehicles/{vehicle['vin']}/fuel")

        assert response.status_code == 401

    async def test_create_fuel_record_validation(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that invalid fuel records are rejected."""
        invalid_payload = {
            "vin": test_vehicle["vin"],
            "date": "2024-01-15",
            "gallons": -12.5,  # Negative gallons should fail
            "cost": 45.00,
            "mileage": 15500,
            "is_full_tank": True,
        }

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/fuel",
            json=invalid_payload,
            headers=auth_headers,
        )

        assert response.status_code == 422  # Validation error

    async def test_fuel_record_pagination(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test fuel record pagination."""
        vehicle = test_vehicle_with_records

        # Test pagination with limit
        response = await client.get(
            f"/api/vehicles/{vehicle['vin']}/fuel?skip=0&limit=5",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["records"]) <= 5

    async def test_fuel_record_hauling_filter(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test fuel record filtering for hauling/towing."""
        vehicle = test_vehicle

        # Create normal fill-up
        await client.post(
            f"/api/vehicles/{vehicle['vin']}/fuel",
            json={
                "vin": vehicle["vin"],
                "date": "2024-01-01",
                "gallons": 12.0,
                "cost": 43.20,
                "mileage": 10000,
                "is_full_tank": True,
                "is_hauling": False,
            },
            headers=auth_headers,
        )

        # Create hauling fill-up
        await client.post(
            f"/api/vehicles/{vehicle['vin']}/fuel",
            json={
                "vin": vehicle["vin"],
                "date": "2024-01-15",
                "gallons": 15.0,
                "cost": 54.00,
                "mileage": 10250,
                "is_full_tank": True,
                "is_hauling": True,
            },
            headers=auth_headers,
        )

        # Test with include_hauling=false
        response = await client.get(
            f"/api/vehicles/{vehicle['vin']}/fuel?include_hauling=false",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Average MPG should exclude hauling records
        assert "average_mpg" in data


@pytest.mark.integration
@pytest.mark.fuel
@pytest.mark.def_records
@pytest.mark.asyncio
class TestFuelDEFSync:
    """Test DEF auto-sync from fuel records."""

    async def test_create_fuel_with_def_creates_linked_def_record(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that creating a fuel record with def_fill_level auto-creates a DEF record."""
        vin = test_vehicle["vin"]

        # Create fuel record with DEF fill level (backend expects 0.00-1.00)
        response = await client.post(
            f"/api/vehicles/{vin}/fuel",
            json={
                "vin": vin,
                "date": "2024-08-01",
                "gallons": 15.0,
                "cost": 54.00,
                "mileage": 60000,
                "is_full_tank": True,
                "def_fill_level": 0.50,
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        fuel_record = response.json()

        # Check DEF records for this vehicle
        def_response = await client.get(
            f"/api/vehicles/{vin}/def",
            headers=auth_headers,
        )
        assert def_response.status_code == 200
        def_data = def_response.json()

        # Find the auto-synced DEF record
        auto_records = [r for r in def_data["records"] if r.get("entry_type") == "auto_fuel_sync"]
        assert len(auto_records) >= 1

        synced = auto_records[-1]
        assert synced["origin_fuel_record_id"] == fuel_record["id"]
        assert float(synced["fill_level"]) == pytest.approx(0.50, abs=0.01)
        assert synced["mileage"] == 60000
        assert synced["date"] == "2024-08-01"

    async def test_create_fuel_without_def_no_def_record(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that creating a fuel record without def_fill_level does NOT create a DEF record."""
        vin = test_vehicle["vin"]

        # Get initial DEF record count
        initial_def = await client.get(
            f"/api/vehicles/{vin}/def",
            headers=auth_headers,
        )
        initial_count = initial_def.json()["total"]

        # Create fuel record WITHOUT DEF level
        response = await client.post(
            f"/api/vehicles/{vin}/fuel",
            json={
                "vin": vin,
                "date": "2024-08-05",
                "gallons": 12.0,
                "cost": 43.20,
                "mileage": 60500,
                "is_full_tank": True,
            },
            headers=auth_headers,
        )
        assert response.status_code == 201

        # DEF record count should not change
        after_def = await client.get(
            f"/api/vehicles/{vin}/def",
            headers=auth_headers,
        )
        assert after_def.json()["total"] == initial_count

    async def test_update_fuel_def_updates_linked_record(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that updating def_fill_level on a fuel record updates the linked DEF record."""
        vin = test_vehicle["vin"]

        # Create fuel record with DEF level
        create_resp = await client.post(
            f"/api/vehicles/{vin}/fuel",
            json={
                "vin": vin,
                "date": "2024-09-01",
                "gallons": 14.0,
                "cost": 50.00,
                "mileage": 62000,
                "is_full_tank": True,
                "def_fill_level": 0.75,
            },
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        fuel_id = create_resp.json()["id"]

        # Update the fuel record with a new DEF level
        update_resp = await client.put(
            f"/api/vehicles/{vin}/fuel/{fuel_id}",
            json={
                "def_fill_level": 0.25,
            },
            headers=auth_headers,
        )
        assert update_resp.status_code == 200

        # Verify the linked DEF record was updated
        def_response = await client.get(
            f"/api/vehicles/{vin}/def",
            headers=auth_headers,
        )
        auto_records = [
            r for r in def_response.json()["records"] if r.get("origin_fuel_record_id") == fuel_id
        ]
        assert len(auto_records) == 1
        assert float(auto_records[0]["fill_level"]) == pytest.approx(0.25, abs=0.01)

    async def test_update_fuel_clear_def_removes_linked_record(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that setting def_fill_level to null removes the linked DEF record."""
        vin = test_vehicle["vin"]

        # Create fuel record with DEF level
        create_resp = await client.post(
            f"/api/vehicles/{vin}/fuel",
            json={
                "vin": vin,
                "date": "2024-10-01",
                "gallons": 13.0,
                "cost": 47.00,
                "mileage": 64000,
                "is_full_tank": True,
                "def_fill_level": 0.60,
            },
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        fuel_id = create_resp.json()["id"]

        # Verify DEF record exists
        def_response = await client.get(
            f"/api/vehicles/{vin}/def",
            headers=auth_headers,
        )
        linked = [
            r for r in def_response.json()["records"] if r.get("origin_fuel_record_id") == fuel_id
        ]
        assert len(linked) == 1

        # Update fuel record with null DEF level (clear it)
        update_resp = await client.put(
            f"/api/vehicles/{vin}/fuel/{fuel_id}",
            json={
                "def_fill_level": None,
            },
            headers=auth_headers,
        )
        assert update_resp.status_code == 200

        # Verify DEF record was removed
        def_after = await client.get(
            f"/api/vehicles/{vin}/def",
            headers=auth_headers,
        )
        linked_after = [
            r for r in def_after.json()["records"] if r.get("origin_fuel_record_id") == fuel_id
        ]
        assert len(linked_after) == 0

    async def test_delete_fuel_cascades_def_record(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that deleting a fuel record also removes the linked DEF record."""
        vin = test_vehicle["vin"]

        # Create fuel record with DEF level
        create_resp = await client.post(
            f"/api/vehicles/{vin}/fuel",
            json={
                "vin": vin,
                "date": "2024-11-01",
                "gallons": 16.0,
                "cost": 58.00,
                "mileage": 66000,
                "is_full_tank": True,
                "def_fill_level": 0.80,
            },
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        fuel_id = create_resp.json()["id"]

        # Verify DEF record exists
        def_response = await client.get(
            f"/api/vehicles/{vin}/def",
            headers=auth_headers,
        )
        linked = [
            r for r in def_response.json()["records"] if r.get("origin_fuel_record_id") == fuel_id
        ]
        assert len(linked) == 1

        # Delete the fuel record
        del_resp = await client.delete(
            f"/api/vehicles/{vin}/fuel/{fuel_id}",
            headers=auth_headers,
        )
        assert del_resp.status_code == 204

        # Verify DEF record was also deleted
        def_after = await client.get(
            f"/api/vehicles/{vin}/def",
            headers=auth_headers,
        )
        linked_after = [
            r for r in def_after.json()["records"] if r.get("origin_fuel_record_id") == fuel_id
        ]
        assert len(linked_after) == 0

    async def test_def_response_includes_entry_type(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that DEF records include entry_type and origin_fuel_record_id in response."""
        vin = test_vehicle["vin"]

        # Create a manual DEF record (purchase)
        manual_resp = await client.post(
            f"/api/vehicles/{vin}/def",
            json={
                "vin": vin,
                "date": "2024-12-01",
                "gallons": 2.5,
                "cost": 15.00,
                "fill_level": 1.0,
            },
            headers=auth_headers,
        )
        assert manual_resp.status_code == 201
        manual_data = manual_resp.json()
        assert manual_data["entry_type"] == "purchase"
        assert manual_data["origin_fuel_record_id"] is None

        # Create a fuel record with DEF → auto-synced DEF record
        fuel_resp = await client.post(
            f"/api/vehicles/{vin}/fuel",
            json={
                "vin": vin,
                "date": "2024-12-15",
                "gallons": 14.0,
                "cost": 50.00,
                "mileage": 68000,
                "is_full_tank": True,
                "def_fill_level": 0.50,
            },
            headers=auth_headers,
        )
        assert fuel_resp.status_code == 201
        fuel_id = fuel_resp.json()["id"]

        # Verify the auto-synced record has correct entry_type
        def_response = await client.get(
            f"/api/vehicles/{vin}/def",
            headers=auth_headers,
        )
        auto_records = [
            r for r in def_response.json()["records"] if r.get("origin_fuel_record_id") == fuel_id
        ]
        assert len(auto_records) == 1
        assert auto_records[0]["entry_type"] == "auto_fuel_sync"

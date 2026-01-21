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

    async def test_fuel_mpg_calculation(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
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

    async def test_partial_fillup_no_mpg(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
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

    async def test_fuel_record_unauthorized(
        self, client: AsyncClient, test_vehicle_with_records
    ):
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

"""
Integration tests for service record routes.

Tests service record CRUD operations and access control.
"""
import pytest
from httpx import AsyncClient
from datetime import date


@pytest.mark.integration
@pytest.mark.service
@pytest.mark.asyncio
class TestServiceRecordRoutes:
    """Test service record API endpoints."""

    async def test_list_service_records(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test listing service records for a vehicle."""
        vehicle = test_vehicle_with_records
        response = await client.get(
            f"/api/vehicles/{vehicle['vin']}/service",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "records" in data
        assert "total" in data
        assert isinstance(data["records"], list)
        assert data["total"] >= 0

    async def test_get_service_record_by_id(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test retrieving a specific service record."""
        vehicle = test_vehicle_with_records

        # First create a service record
        create_response = await client.post(
            f"/api/vehicles/{vehicle['vin']}/service",
            json={
                "date": "2024-01-15",
                "service_type": "Oil Change",
                "cost": 45.99,
                "odometer": 15500,
                "notes": "Changed oil and filter",
            },
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        record = create_response.json()

        # Get the service record
        response = await client.get(
            f"/api/vehicles/{vehicle['vin']}/service/{record['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == record["id"]
        assert data["service_type"] == "Oil Change"
        assert data["cost"] == 45.99

    async def test_create_service_record(
        self, client: AsyncClient, auth_headers, test_vehicle, sample_service_payload
    ):
        """Test creating a new service record."""
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/service",
            json=sample_service_payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["service_type"] == sample_service_payload["service_type"]
        assert data["cost"] == sample_service_payload["cost"]
        assert "id" in data

    async def test_update_service_record(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test updating a service record."""
        vehicle = test_vehicle_with_records

        # Create a service record
        create_response = await client.post(
            f"/api/vehicles/{vehicle['vin']}/service",
            json={
                "date": "2024-01-15",
                "service_type": "Oil Change",
                "cost": 45.99,
                "odometer": 15500,
            },
            headers=auth_headers,
        )
        record = create_response.json()

        # Update the record
        update_data = {
            "cost": 55.99,
            "notes": "Updated cost and added notes",
        }

        response = await client.put(
            f"/api/vehicles/{vehicle['vin']}/service/{record['id']}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["cost"] == 55.99
        assert data["notes"] == "Updated cost and added notes"

    async def test_delete_service_record(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test deleting a service record."""
        vehicle = test_vehicle_with_records

        # Create a service record
        create_response = await client.post(
            f"/api/vehicles/{vehicle['vin']}/service",
            json={
                "date": "2024-01-15",
                "service_type": "Oil Change",
                "cost": 45.99,
                "odometer": 15500,
            },
            headers=auth_headers,
        )
        record = create_response.json()

        # Delete the record
        response = await client.delete(
            f"/api/vehicles/{vehicle['vin']}/service/{record['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(
            f"/api/vehicles/{vehicle['vin']}/service/{record['id']}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_service_record_unauthorized(
        self, client: AsyncClient, test_vehicle_with_records
    ):
        """Test that unauthenticated users cannot access service records."""
        vehicle = test_vehicle_with_records
        response = await client.get(f"/api/vehicles/{vehicle['vin']}/service")

        assert response.status_code == 401

    async def test_create_service_record_validation(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that invalid service records are rejected."""
        invalid_payload = {
            "date": "2024-01-15",
            "service_type": "Oil Change",
            "cost": -45.99,  # Negative cost should fail
            "odometer": 15500,
        }

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/service",
            json=invalid_payload,
            headers=auth_headers,
        )

        assert response.status_code == 422  # Validation error

    async def test_service_record_pagination(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test service record pagination."""
        vehicle = test_vehicle_with_records

        # Test pagination with limit
        response = await client.get(
            f"/api/vehicles/{vehicle['vin']}/service?skip=0&limit=5",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["records"]) <= 5

    async def test_service_record_with_vehicle_not_found(
        self, client: AsyncClient, auth_headers
    ):
        """Test creating service record for non-existent vehicle."""
        response = await client.post(
            "/api/vehicles/INVALIDVIN1234567/service",
            json={
                "date": "2024-01-15",
                "service_type": "Oil Change",
                "cost": 45.99,
                "odometer": 15500,
            },
            headers=auth_headers,
        )

        assert response.status_code == 404

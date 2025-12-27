"""
Integration tests for vehicle routes.

Tests vehicle CRUD operations and access control.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.vehicle
@pytest.mark.asyncio
class TestVehicleRoutes:
    """Test vehicle API endpoints."""

    async def test_list_vehicles(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test listing user's vehicles."""
        response = await client.get("/api/vehicles", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        # Should include our test vehicle
        vehicle_ids = [v["id"] for v in data]
        assert test_vehicle["id"] in vehicle_ids

    async def test_get_vehicle_by_id(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test retrieving a specific vehicle."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_vehicle["id"]
        assert data["vin"] == test_vehicle["vin"]
        assert data["year"] == test_vehicle["year"]

    async def test_create_vehicle(
        self, client: AsyncClient, auth_headers, sample_vehicle_payload
    ):
        """Test creating a new vehicle."""
        response = await client.post(
            "/api/vehicles",
            json=sample_vehicle_payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["vin"] == sample_vehicle_payload["vin"]
        assert data["year"] == sample_vehicle_payload["year"]
        assert "id" in data

    async def test_update_vehicle(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test updating a vehicle."""
        update_data = {
            "license_plate": "UPDATED-123",
            "current_odometer": 16000,
        }

        response = await client.put(
            f"/api/vehicles/{test_vehicle['id']}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["license_plate"] == "UPDATED-123"
        assert data["current_odometer"] == 16000

    async def test_delete_vehicle(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test deleting a vehicle."""
        response = await client.delete(
            f"/api/vehicles/{test_vehicle['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(
            f"/api/vehicles/{test_vehicle['id']}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_get_vehicle_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot access vehicles."""
        response = await client.get(f"/api/vehicles/{test_vehicle['id']}")

        assert response.status_code == 401

    async def test_create_vehicle_invalid_vin(self, client: AsyncClient, auth_headers):
        """Test that invalid VINs are rejected."""
        invalid_payload = {
            "vin": "INVALID",  # Too short
            "year": 2023,
            "make": "Test",
            "model": "Car",
        }

        response = await client.post(
            "/api/vehicles",
            json=invalid_payload,
            headers=auth_headers,
        )

        assert response.status_code == 422  # Validation error

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
        # API returns {"vehicles": [...], "total": N}
        assert "vehicles" in data
        assert "total" in data
        assert isinstance(data["vehicles"], list)
        assert len(data["vehicles"]) >= 1
        # Should include our test vehicle (identified by VIN, not id)
        vehicle_vins = [v["vin"] for v in data["vehicles"]]
        assert test_vehicle["vin"] in vehicle_vins

    async def test_get_vehicle_by_vin(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test retrieving a specific vehicle by VIN."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["vin"] == test_vehicle["vin"]
        assert data["year"] == test_vehicle["year"]
        assert data["make"] == test_vehicle["make"]

    async def test_create_vehicle(self, client: AsyncClient, auth_headers, sample_vehicle_payload):
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
        assert data["nickname"] == sample_vehicle_payload["nickname"]

    async def test_update_vehicle(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test updating a vehicle."""
        update_data = {
            "license_plate": "UPDATED-123",
        }

        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["license_plate"] == "UPDATED-123"

    async def test_delete_vehicle(self, client: AsyncClient, auth_headers, db_session):
        """Test deleting a vehicle."""
        from app.models.vehicle import Vehicle

        # Create a vehicle specifically for deletion
        delete_vehicle = Vehicle(
            vin="1HGCM82633A999999",
            user_id=1,  # test user
            nickname="Delete Test Vehicle",
            vehicle_type="Car",
            year=2020,
            make="Test",
            model="Delete",
        )
        db_session.add(delete_vehicle)
        await db_session.commit()

        response = await client.delete(
            f"/api/vehicles/{delete_vehicle.vin}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(
            f"/api/vehicles/{delete_vehicle.vin}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_get_vehicle_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot access vehicles."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}")

        assert response.status_code == 401

    async def test_create_vehicle_invalid_vin(self, client: AsyncClient, auth_headers):
        """Test that invalid VINs are rejected."""
        invalid_payload = {
            "vin": "INVALID",  # Too short (must be 17 chars)
            "nickname": "Test Vehicle",
            "vehicle_type": "Car",
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

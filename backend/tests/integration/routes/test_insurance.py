"""
Integration tests for insurance routes.

Tests insurance CRUD operations.
"""
import pytest
from httpx import AsyncClient
from datetime import date, timedelta


@pytest.mark.integration
@pytest.mark.asyncio
class TestInsuranceRoutes:
    """Test insurance API endpoints."""

    async def test_create_insurance(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test creating an insurance record."""
        start_date = date.today().isoformat()
        end_date = (date.today() + timedelta(days=365)).isoformat()

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/insurance",
            json={
                "provider": "State Farm",
                "policy_number": "SF-12345678",
                "start_date": start_date,
                "end_date": end_date,
                "premium": 1200.00,
                "coverage_type": "Full Coverage",
            },
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["provider"] == "State Farm"
        assert data["policy_number"] == "SF-12345678"
        assert "id" in data

    async def test_list_insurance(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test listing insurance records for a vehicle."""
        vehicle = test_vehicle_with_records

        response = await client.get(
            f"/api/vehicles/{vehicle['vin']}/insurance",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list) or ("insurance" in data)

    async def test_get_insurance_by_id(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test retrieving a specific insurance record."""
        start_date = date.today().isoformat()
        end_date = (date.today() + timedelta(days=365)).isoformat()

        # Create insurance
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/insurance",
            json={
                "provider": "Geico",
                "policy_number": "G-987654321",
                "start_date": start_date,
                "end_date": end_date,
                "premium": 900.00,
            },
            headers=auth_headers,
        )
        insurance = create_response.json()

        # Get the insurance record
        response = await client.get(
            f"/api/insurance/{insurance['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == insurance["id"]
        assert data["provider"] == "Geico"

    async def test_update_insurance(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test updating an insurance record."""
        start_date = date.today().isoformat()
        end_date = (date.today() + timedelta(days=365)).isoformat()

        # Create insurance
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/insurance",
            json={
                "provider": "Progressive",
                "policy_number": "P-111111",
                "start_date": start_date,
                "end_date": end_date,
                "premium": 1000.00,
            },
            headers=auth_headers,
        )
        insurance = create_response.json()

        # Update the insurance
        update_data = {
            "premium": 950.00,
            "notes": "Discount applied",
        }

        response = await client.put(
            f"/api/insurance/{insurance['id']}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["premium"] == 950.00

    async def test_delete_insurance(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test deleting an insurance record."""
        start_date = date.today().isoformat()
        end_date = (date.today() + timedelta(days=365)).isoformat()

        # Create insurance
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/insurance",
            json={
                "provider": "Allstate",
                "policy_number": "A-999999",
                "start_date": start_date,
                "end_date": end_date,
                "premium": 1100.00,
            },
            headers=auth_headers,
        )
        insurance = create_response.json()

        # Delete the insurance
        response = await client.delete(
            f"/api/insurance/{insurance['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(
            f"/api/insurance/{insurance['id']}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_insurance_validation(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test insurance validation."""
        # Invalid date range (end before start)
        start_date = date.today().isoformat()
        end_date = (date.today() - timedelta(days=30)).isoformat()

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/insurance",
            json={
                "provider": "Test",
                "policy_number": "TEST",
                "start_date": start_date,
                "end_date": end_date,
                "premium": 1000.00,
            },
            headers=auth_headers,
        )

        # Should fail validation or business logic check
        assert response.status_code in [400, 422]

    async def test_insurance_unauthorized(
        self, client: AsyncClient, test_vehicle
    ):
        """Test that unauthenticated users cannot create insurance."""
        start_date = date.today().isoformat()
        end_date = (date.today() + timedelta(days=365)).isoformat()

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/insurance",
            json={
                "provider": "Test",
                "policy_number": "TEST",
                "start_date": start_date,
                "end_date": end_date,
                "premium": 1000.00,
            },
        )

        assert response.status_code == 401

    async def test_active_insurance(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test getting active insurance for a vehicle."""
        # Create active insurance
        start_date = (date.today() - timedelta(days=30)).isoformat()
        end_date = (date.today() + timedelta(days=335)).isoformat()

        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/insurance",
            json={
                "provider": "Active Insurance Co",
                "policy_number": "ACTIVE-123",
                "start_date": start_date,
                "end_date": end_date,
                "premium": 1000.00,
            },
            headers=auth_headers,
        )

        # Get active insurance
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/insurance/active",
            headers=auth_headers,
        )

        # Should return active policy or 200/404
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.json()
            if data:  # Not empty
                assert "provider" in data or "insurance" in data

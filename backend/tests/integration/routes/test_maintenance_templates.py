"""
Integration tests for maintenance template routes.

Tests template search, application, and management.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestMaintenanceTemplateRoutes:
    """Test maintenance template API endpoints."""

    async def test_search_template_not_found(self, client: AsyncClient, auth_headers):
        """Test searching for a template that doesn't exist."""
        response = await client.get(
            "/api/maintenance-templates/search",
            params={
                "year": 1900,
                "make": "NonExistent",
                "model": "FakeModel",
                "duty_type": "normal",
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["found"] is False
        assert "error" in data or data.get("template_data") is None

    async def test_search_template_with_fuel_type(self, client: AsyncClient, auth_headers):
        """Test searching for a template with fuel type filter."""
        response = await client.get(
            "/api/maintenance-templates/search",
            params={
                "year": 2020,
                "make": "Toyota",
                "model": "Camry",
                "duty_type": "normal",
                "fuel_type": "Gasoline",
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Response contains found field
        assert "found" in data

    async def test_search_template_duty_types(self, client: AsyncClient, auth_headers):
        """Test searching for templates with different duty types."""
        # Normal duty
        response_normal = await client.get(
            "/api/maintenance-templates/search",
            params={
                "year": 2020,
                "make": "Ford",
                "model": "F-150",
                "duty_type": "normal",
            },
            headers=auth_headers,
        )
        assert response_normal.status_code == 200

        # Severe duty
        response_severe = await client.get(
            "/api/maintenance-templates/search",
            params={
                "year": 2020,
                "make": "Ford",
                "model": "F-150",
                "duty_type": "severe",
            },
            headers=auth_headers,
        )
        assert response_severe.status_code == 200

    async def test_get_vehicle_templates_empty(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test getting templates for vehicle with no templates applied."""
        response = await client.get(
            f"/api/maintenance-templates/vehicles/{test_vehicle['vin']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "templates" in data
        assert "total" in data
        assert isinstance(data["templates"], list)

    async def test_get_vehicle_templates_not_found(self, client: AsyncClient, auth_headers):
        """Test getting templates for non-existent vehicle."""
        response = await client.get(
            "/api/maintenance-templates/vehicles/NONEXISTENT12345VN",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_delete_template_not_found(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test deleting a template record that doesn't exist."""
        response = await client.delete(
            f"/api/maintenance-templates/vehicles/{test_vehicle['vin']}/99999",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_templates_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot access templates."""
        response = await client.get(f"/api/maintenance-templates/vehicles/{test_vehicle['vin']}")

        assert response.status_code == 401

    async def test_search_template_unauthorized(self, client: AsyncClient):
        """Test that unauthenticated users cannot search templates."""
        response = await client.get(
            "/api/maintenance-templates/search",
            params={
                "year": 2020,
                "make": "Toyota",
                "model": "Camry",
            },
        )

        assert response.status_code == 401

    async def test_apply_template_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot apply templates."""
        response = await client.post(
            "/api/maintenance-templates/apply",
            json={
                "vin": test_vehicle["vin"],
                "duty_type": "normal",
            },
        )

        assert response.status_code == 401

    async def test_apply_template_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test applying template to non-existent vehicle."""
        # Use a valid VIN format (17 chars) that doesn't exist in DB
        response = await client.post(
            "/api/maintenance-templates/apply",
            json={
                "vin": "1HGBH000000000000",  # 17 characters
                "duty_type": "normal",
            },
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_apply_template_to_vehicle(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test applying a template to a vehicle."""
        response = await client.post(
            "/api/maintenance-templates/apply",
            json={
                "vin": test_vehicle["vin"],
                "duty_type": "normal",
            },
            headers=auth_headers,
        )

        # Either succeeds or returns success=False if no template found
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        if data["success"]:
            assert "reminders_created" in data
            assert "template_source" in data

    async def test_apply_template_with_mileage(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test applying template with current mileage."""
        response = await client.post(
            "/api/maintenance-templates/apply",
            json={
                "vin": test_vehicle["vin"],
                "duty_type": "normal",
                "current_mileage": 50000,
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "success" in data

    async def test_apply_template_severe_duty(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test applying severe duty template."""
        response = await client.post(
            "/api/maintenance-templates/apply",
            json={
                "vin": test_vehicle["vin"],
                "duty_type": "severe",
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "success" in data

"""
Integration tests for maintenance schedule routes.

Tests maintenance schedule CRUD operations and status tracking.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestMaintenanceScheduleRoutes:
    """Test maintenance schedule API endpoints."""

    async def test_list_schedule_items(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test listing maintenance schedule items for a vehicle."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "due_soon_count" in data
        assert "overdue_count" in data
        assert "on_track_count" in data
        assert "never_performed_count" in data
        assert isinstance(data["items"], list)

    async def test_get_schedule_item_by_id(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test retrieving a specific schedule item."""
        # First create a schedule item
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule",
            json={
                "vin": test_vehicle["vin"],
                "name": "Oil Change",
                "component_category": "Engine",
                "item_type": "service",
                "interval_months": 6,
                "interval_miles": 5000,
            },
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        item = create_response.json()

        # Get the schedule item
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule/{item['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == item["id"]
        assert data["name"] == "Oil Change"
        assert data["component_category"] == "Engine"

    async def test_create_schedule_item(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating a new maintenance schedule item."""
        payload = {
            "vin": test_vehicle["vin"],
            "name": "Tire Rotation",
            "component_category": "Tires",
            "item_type": "service",
            "interval_months": 6,
            "interval_miles": 7500,
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == payload["name"]
        assert data["component_category"] == payload["component_category"]
        assert data["item_type"] == payload["item_type"]
        assert data["interval_months"] == payload["interval_months"]
        assert data["interval_miles"] == payload["interval_miles"]
        assert "id" in data
        assert "created_at" in data
        assert data["status"] == "never_performed"

    async def test_update_schedule_item(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test updating a maintenance schedule item."""
        # Create a schedule item
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule",
            json={
                "vin": test_vehicle["vin"],
                "name": "Brake Inspection",
                "component_category": "Brakes",
                "item_type": "inspection",
                "interval_months": 12,
            },
            headers=auth_headers,
        )
        item = create_response.json()

        # Update the item
        update_data = {
            "name": "Brake Pad Inspection",
            "interval_months": 6,
            "interval_miles": 10000,
        }

        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule/{item['id']}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Brake Pad Inspection"
        assert data["interval_months"] == 6
        assert data["interval_miles"] == 10000

    async def test_delete_schedule_item(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test deleting a maintenance schedule item."""
        # Create a schedule item
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule",
            json={
                "vin": test_vehicle["vin"],
                "name": "Fluid Check",
                "component_category": "Fluids",
                "item_type": "inspection",
                "interval_months": 3,
            },
            headers=auth_headers,
        )
        item = create_response.json()

        # Delete the item
        response = await client.delete(
            f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule/{item['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule/{item['id']}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_schedule_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot access maintenance schedule."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule")

        assert response.status_code == 401

    async def test_create_schedule_validation(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that invalid schedule items are rejected."""
        # Name is required
        invalid_payload = {
            "vin": test_vehicle["vin"],
            "name": "",  # Empty name should fail
            "component_category": "Engine",
            "item_type": "service",
        }

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule",
            json=invalid_payload,
            headers=auth_headers,
        )

        assert response.status_code == 422  # Validation error

    async def test_schedule_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test maintenance schedule with non-existent vehicle."""
        response = await client.get(
            "/api/vehicles/NONEXISTENT12345VN/maintenance-schedule",
            headers=auth_headers,
        )

        # get_vehicle_or_403 returns 403 if vehicle not found
        assert response.status_code in [403, 404]

    async def test_schedule_item_not_found(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test get schedule item with non-existent ID."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule/99999",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_create_service_type_item(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating a service-type maintenance item."""
        payload = {
            "vin": test_vehicle["vin"],
            "name": "Transmission Fluid Change",
            "component_category": "Transmission",
            "item_type": "service",
            "interval_months": 24,
            "interval_miles": 30000,
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["item_type"] == "service"

    async def test_create_inspection_type_item(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test creating an inspection-type maintenance item."""
        payload = {
            "vin": test_vehicle["vin"],
            "name": "Battery Test",
            "component_category": "Electrical",
            "item_type": "inspection",
            "interval_months": 12,
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["item_type"] == "inspection"

    async def test_component_categories(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating items with all valid component categories."""
        categories = [
            "Engine",
            "Transmission",
            "Brakes",
            "Tires",
            "Electrical",
            "HVAC",
            "Fluids",
            "Suspension",
            "Body/Exterior",
            "Interior",
            "Exhaust",
            "Fuel System",
            "Other",
        ]

        for i, category in enumerate(categories):
            response = await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule",
                json={
                    "vin": test_vehicle["vin"],
                    "name": f"{category} Check {i}",
                    "component_category": category,
                    "item_type": "inspection",
                    "interval_months": 12,
                },
                headers=auth_headers,
            )
            assert response.status_code == 201, f"Failed for category: {category}"
            data = response.json()
            assert data["component_category"] == category

    async def test_invalid_component_category(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that invalid component category is rejected."""
        payload = {
            "vin": test_vehicle["vin"],
            "name": "Invalid Category Item",
            "component_category": "InvalidCategory",
            "item_type": "service",
            "interval_months": 6,
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 422

    async def test_invalid_item_type(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test that invalid item type is rejected."""
        payload = {
            "vin": test_vehicle["vin"],
            "name": "Invalid Type Item",
            "component_category": "Engine",
            "item_type": "invalid_type",
            "interval_months": 6,
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 422

    async def test_schedule_item_intervals(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating items with different interval combinations."""
        # Only months
        response1 = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule",
            json={
                "vin": test_vehicle["vin"],
                "name": "Monthly Check",
                "component_category": "Fluids",
                "item_type": "inspection",
                "interval_months": 1,
            },
            headers=auth_headers,
        )
        assert response1.status_code == 201

        # Only miles
        response2 = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule",
            json={
                "vin": test_vehicle["vin"],
                "name": "Mileage Check",
                "component_category": "Tires",
                "item_type": "inspection",
                "interval_miles": 5000,
            },
            headers=auth_headers,
        )
        assert response2.status_code == 201

        # Both months and miles
        response3 = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule",
            json={
                "vin": test_vehicle["vin"],
                "name": "Combined Check",
                "component_category": "Engine",
                "item_type": "service",
                "interval_months": 6,
                "interval_miles": 7500,
            },
            headers=auth_headers,
        )
        assert response3.status_code == 201

    async def test_list_schedule_with_status_filter(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test filtering schedule items by status."""
        # Create an item (it will be never_performed)
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule",
            json={
                "vin": test_vehicle["vin"],
                "name": "Filter Test Item",
                "component_category": "Other",
                "item_type": "inspection",
                "interval_months": 1,
            },
            headers=auth_headers,
        )

        # Filter by never_performed
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule?status=never_performed",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # All returned items should be never_performed
        for item in data["items"]:
            assert item["status"] == "never_performed"

    async def test_schedule_pagination(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test maintenance schedule pagination."""
        # Create multiple items
        for i in range(5):
            await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule",
                json={
                    "vin": test_vehicle["vin"],
                    "name": f"Pagination Item {i}",
                    "component_category": "Other",
                    "item_type": "inspection",
                    "interval_months": 12,
                },
                headers=auth_headers,
            )

        # Test pagination with limit
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule?skip=0&limit=3",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) <= 3

    async def test_partial_update_schedule_item(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test partial update of schedule item."""
        # Create a schedule item
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule",
            json={
                "vin": test_vehicle["vin"],
                "name": "Partial Update Test",
                "component_category": "Brakes",
                "item_type": "service",
                "interval_months": 12,
                "interval_miles": 15000,
            },
            headers=auth_headers,
        )
        item = create_response.json()

        # Update only interval_months
        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/maintenance-schedule/{item['id']}",
            json={"interval_months": 6},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        # Name unchanged
        assert data["name"] == "Partial Update Test"
        # interval_miles unchanged
        assert data["interval_miles"] == 15000
        # interval_months updated
        assert data["interval_months"] == 6

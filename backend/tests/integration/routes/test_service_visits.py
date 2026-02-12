"""
Integration tests for service visit routes.

Tests service visit CRUD operations including line items.
"""

from datetime import datetime

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestServiceVisitRoutes:
    """Test service visit API endpoints."""

    async def test_list_service_visits(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test listing service visits for a vehicle."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "visits" in data
        assert "total" in data
        assert isinstance(data["visits"], list)

    async def test_get_service_visit_by_id(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test retrieving a specific service visit."""
        # First create a service visit
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits",
            json={
                "date": "2024-01-15",
                "mileage": 50000,
                "service_category": "Maintenance",
                "notes": "Regular maintenance visit",
                "line_items": [
                    {
                        "description": "Oil Change",
                        "cost": 45.99,
                    }
                ],
            },
            headers=auth_headers,
        )
        assert create_response.status_code == 201
        visit = create_response.json()

        # Get the service visit
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits/{visit['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == visit["id"]
        assert data["mileage"] == 50000
        assert data["service_category"] == "Maintenance"

    async def test_create_service_visit(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating a new service visit."""
        payload = {
            "date": datetime.now().date().isoformat(),
            "mileage": 55000,
            "service_category": "Maintenance",
            "notes": "Test service visit",
            "line_items": [
                {
                    "description": "Tire Rotation",
                    "cost": 25.00,
                    "notes": "Rotated and balanced",
                },
                {
                    "description": "Brake Inspection",
                    "cost": 0,
                    "is_inspection": True,
                    "inspection_result": "passed",
                    "inspection_severity": "green",
                },
            ],
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["mileage"] == payload["mileage"]
        assert data["service_category"] == payload["service_category"]
        assert "id" in data
        assert "created_at" in data
        assert len(data["line_items"]) == 2

    async def test_update_service_visit(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test updating a service visit."""
        # Create a service visit
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits",
            json={
                "date": "2024-02-01",
                "mileage": 52000,
                "service_category": "Inspection",
                "line_items": [
                    {
                        "description": "State Inspection",
                        "cost": 25.50,
                        "is_inspection": True,
                        "inspection_result": "passed",
                    }
                ],
            },
            headers=auth_headers,
        )
        visit = create_response.json()

        # Update the visit
        update_data = {
            "notes": "Updated notes after inspection",
            "mileage": 52100,
        }

        response = await client.put(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits/{visit['id']}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["notes"] == "Updated notes after inspection"
        assert data["mileage"] == 52100

    async def test_delete_service_visit(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test deleting a service visit."""
        # Create a service visit
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits",
            json={
                "date": "2024-03-01",
                "mileage": 53000,
                "line_items": [
                    {
                        "description": "Test Service",
                        "cost": 10.00,
                    }
                ],
            },
            headers=auth_headers,
        )
        visit = create_response.json()

        # Delete the visit
        response = await client.delete(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits/{visit['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it's deleted
        get_response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits/{visit['id']}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_service_visit_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot access service visits."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}/service-visits")

        assert response.status_code == 401

    async def test_create_service_visit_validation(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that invalid service visits are rejected."""
        # line_items is required and must have at least 1 item
        invalid_payload = {
            "date": "2024-01-15",
            "mileage": 50000,
            "line_items": [],  # Empty line items should fail
        }

        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits",
            json=invalid_payload,
            headers=auth_headers,
        )

        assert response.status_code == 422  # Validation error

    async def test_service_visit_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test service visits with non-existent vehicle."""
        response = await client.get(
            "/api/vehicles/NONEXISTENT12345VN/service-visits",
            headers=auth_headers,
        )

        # Returns 403 from get_vehicle_or_403
        assert response.status_code in [403, 404]

    async def test_service_visit_not_found(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test get service visit with non-existent ID."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits/99999",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_add_line_item_to_visit(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test adding a line item to an existing service visit."""
        # Create a service visit
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits",
            json={
                "date": "2024-04-01",
                "mileage": 54000,
                "line_items": [
                    {
                        "description": "Initial Service",
                        "cost": 100.00,
                    }
                ],
            },
            headers=auth_headers,
        )
        visit = create_response.json()
        initial_count = len(visit["line_items"])

        # Add a line item
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits/{visit['id']}/line-items",
            json={
                "description": "Additional Service",
                "cost": 50.00,
                "notes": "Added later",
            },
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["description"] == "Additional Service"
        assert float(data["cost"]) == 50.00

        # Verify visit now has one more line item
        get_response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits/{visit['id']}",
            headers=auth_headers,
        )
        updated_visit = get_response.json()
        assert len(updated_visit["line_items"]) == initial_count + 1

    async def test_delete_line_item_from_visit(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test deleting a line item from a service visit."""
        # Create a service visit with multiple line items
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits",
            json={
                "date": "2024-05-01",
                "mileage": 55000,
                "line_items": [
                    {"description": "Service 1", "cost": 50.00},
                    {"description": "Service 2", "cost": 75.00},
                ],
            },
            headers=auth_headers,
        )
        visit = create_response.json()
        line_item_to_delete = visit["line_items"][0]

        # Delete a line item
        response = await client.delete(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits/{visit['id']}/line-items/{line_item_to_delete['id']}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify visit now has one less line item
        get_response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits/{visit['id']}",
            headers=auth_headers,
        )
        updated_visit = get_response.json()
        assert len(updated_visit["line_items"]) == 1

    async def test_service_visit_with_inspection(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test creating a service visit with inspection items."""
        payload = {
            "date": datetime.now().date().isoformat(),
            "mileage": 56000,
            "service_category": "Inspection",
            "line_items": [
                {
                    "description": "Brake Pad Inspection",
                    "cost": 0,
                    "is_inspection": True,
                    "inspection_result": "failed",
                    "inspection_severity": "red",
                    "notes": "Pads at 10%, need replacement",
                },
            ],
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["has_failed_inspections"] is True
        assert data["line_items"][0]["is_inspection"] is True
        assert data["line_items"][0]["inspection_result"] == "failed"
        assert data["line_items"][0]["is_failed_inspection"] is True

    async def test_service_visit_cost_calculation(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that service visit costs are calculated correctly."""
        payload = {
            "date": datetime.now().date().isoformat(),
            "mileage": 57000,
            "tax_amount": 10.00,
            "shop_supplies": 5.00,
            "line_items": [
                {"description": "Service 1", "cost": 100.00},
                {"description": "Service 2", "cost": 50.00},
            ],
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits",
            json=payload,
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        # subtotal should be sum of line item costs: 100 + 50 = 150
        assert float(data["subtotal"]) == 150.00
        # calculated_total_cost should include tax and fees: 150 + 10 + 5 = 165
        assert float(data["calculated_total_cost"]) == 165.00

    async def test_service_visit_pagination(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test service visit pagination."""
        # Create multiple service visits
        for i in range(5):
            await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/service-visits",
                json={
                    "date": f"2024-0{i + 1}-15",
                    "mileage": 60000 + (i * 1000),
                    "line_items": [{"description": f"Service {i}", "cost": 50.00}],
                },
                headers=auth_headers,
            )

        # Test pagination with limit
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits?skip=0&limit=3",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["visits"]) <= 3

    async def test_total_cost_auto_computed_on_create(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Create visit without total_cost; verify it's populated from line items + fees."""
        payload = {
            "date": "2024-08-01",
            "mileage": 80000,
            "tax_amount": 5.00,
            "shop_supplies": 2.50,
            "line_items": [
                {"description": "Battery Replacement", "cost": 180.00},
            ],
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits",
            json=payload,
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        # total_cost = 180 + 5 + 2.50 = 187.50
        assert float(data["total_cost"]) == 187.50
        assert float(data["calculated_total_cost"]) == 187.50

    async def test_total_cost_overwritten_on_create(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Create visit with explicit total_cost that differs; verify computed value wins."""
        payload = {
            "date": "2024-08-02",
            "mileage": 80100,
            "total_cost": 999.99,  # Wrong value — should be overwritten
            "line_items": [
                {"description": "Alignment", "cost": 89.00},
            ],
        }
        response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits",
            json=payload,
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        # total_cost should be computed from line items, not caller-provided
        assert float(data["total_cost"]) == 89.00

    async def test_total_cost_recomputed_on_line_item_add(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Add line item to visit; verify total_cost is refreshed."""
        # Create visit
        create_response = await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits",
            json={
                "date": "2024-08-03",
                "mileage": 80200,
                "line_items": [{"description": "Oil Change", "cost": 45.00}],
            },
            headers=auth_headers,
        )
        visit = create_response.json()
        assert float(visit["total_cost"]) == 45.00

        # Add another line item
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits/{visit['id']}/line-items",
            json={"description": "Filter Replacement", "cost": 15.00},
            headers=auth_headers,
        )

        # Re-fetch and verify total_cost updated
        get_response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits/{visit['id']}",
            headers=auth_headers,
        )
        updated = get_response.json()
        assert float(updated["total_cost"]) == 60.00  # 45 + 15

    async def test_service_category_options(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test creating service visits with all valid categories."""
        categories = ["Maintenance", "Inspection", "Collision", "Upgrades", "Detailing"]

        for i, category in enumerate(categories):
            response = await client.post(
                f"/api/vehicles/{test_vehicle['vin']}/service-visits",
                json={
                    "date": f"2024-06-{i + 1:02d}",
                    "mileage": 70000 + (i * 100),
                    "service_category": category,
                    "line_items": [{"description": f"{category} service", "cost": 100.00}],
                },
                headers=auth_headers,
            )
            assert response.status_code == 201, f"Failed for category: {category}"
            data = response.json()
            assert data["service_category"] == category

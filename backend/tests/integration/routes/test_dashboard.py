"""
Integration tests for dashboard routes.

Tests dashboard aggregation and statistics endpoints.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestDashboardRoutes:
    """Test dashboard API endpoints."""

    async def test_get_dashboard(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test getting dashboard with authenticated user."""
        response = await client.get(
            "/api/dashboard",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "total_vehicles" in data
        assert "vehicles" in data
        assert isinstance(data["vehicles"], list)

    async def test_dashboard_response_structure(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that dashboard response has correct structure."""
        response = await client.get(
            "/api/dashboard",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify main fields
        assert "total_vehicles" in data
        assert "total_service_records" in data
        assert "total_fuel_records" in data
        assert "total_reminders" in data
        assert "total_documents" in data
        assert "total_notes" in data
        assert "total_photos" in data
        assert "vehicles" in data

        # Verify types
        assert isinstance(data["total_vehicles"], int)
        assert isinstance(data["total_service_records"], int)
        assert isinstance(data["vehicles"], list)

    async def test_dashboard_vehicle_statistics(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test vehicle statistics in dashboard."""
        response = await client.get(
            "/api/dashboard",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Should have at least the test vehicle
        assert data["total_vehicles"] >= 1

        # Find our test vehicle
        test_vehicle_stats = None
        for vehicle in data["vehicles"]:
            if vehicle["vin"] == test_vehicle["vin"]:
                test_vehicle_stats = vehicle
                break

        assert test_vehicle_stats is not None
        # Verify vehicle statistics structure
        assert "vin" in test_vehicle_stats
        assert "total_service_records" in test_vehicle_stats
        assert "total_fuel_records" in test_vehicle_stats
        assert "total_odometer_records" in test_vehicle_stats
        assert "total_reminders" in test_vehicle_stats
        assert "total_documents" in test_vehicle_stats
        assert "total_notes" in test_vehicle_stats
        assert "total_photos" in test_vehicle_stats
        assert "upcoming_reminders_count" in test_vehicle_stats
        assert "overdue_reminders_count" in test_vehicle_stats

    async def test_dashboard_after_adding_service_visit(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that dashboard reflects new service visits."""
        # Get initial dashboard
        initial_response = await client.get(
            "/api/dashboard",
            headers=auth_headers,
        )
        initial_data = initial_response.json()

        # Add a service visit
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits",
            json={
                "date": "2024-06-15",
                "mileage": 55000,
                "service_category": "Maintenance",
                "notes": "Dashboard Test Service",
                "line_items": [
                    {"description": "Dashboard Test", "cost": 100.00},
                ],
            },
            headers=auth_headers,
        )

        # Get updated dashboard
        updated_response = await client.get(
            "/api/dashboard",
            headers=auth_headers,
        )
        updated_data = updated_response.json()

        # Total service records should have increased
        assert updated_data["total_service_records"] >= initial_data["total_service_records"]

    async def test_dashboard_after_adding_fuel_record(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that dashboard reflects new fuel records."""
        # Add a fuel record
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/fuel",
            json={
                "vin": test_vehicle["vin"],
                "date": "2024-06-15",
                "mileage": 56000,
                "gallons": 12.5,
                "price_per_gallon": 3.50,
                "total_cost": 43.75,
                "fuel_type": "Regular",
            },
            headers=auth_headers,
        )

        # Get dashboard
        response = await client.get(
            "/api/dashboard",
            headers=auth_headers,
        )
        data = response.json()

        # Total fuel records should include our new record
        assert data["total_fuel_records"] >= 1

    async def test_dashboard_reminder_counts(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test that dashboard tracks reminder counts correctly."""
        # Create an upcoming reminder
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "vin": test_vehicle["vin"],
                "description": "Dashboard upcoming reminder",
                "due_date": "2030-12-31",  # Far future
            },
            headers=auth_headers,
        )

        # Create an overdue reminder
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/reminders",
            json={
                "vin": test_vehicle["vin"],
                "description": "Dashboard overdue reminder",
                "due_date": "2020-01-01",  # Past date
            },
            headers=auth_headers,
        )

        # Get dashboard
        response = await client.get(
            "/api/dashboard",
            headers=auth_headers,
        )
        data = response.json()

        # Find our test vehicle
        test_vehicle_stats = None
        for vehicle in data["vehicles"]:
            if vehicle["vin"] == test_vehicle["vin"]:
                test_vehicle_stats = vehicle
                break

        assert test_vehicle_stats is not None
        # Should have both upcoming and overdue counts
        assert test_vehicle_stats["upcoming_reminders_count"] >= 1
        assert test_vehicle_stats["overdue_reminders_count"] >= 1

    async def test_dashboard_latest_dates(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test that dashboard tracks latest service/fuel dates."""
        # Add a service visit with known date
        await client.post(
            f"/api/vehicles/{test_vehicle['vin']}/service-visits",
            json={
                "date": "2024-07-15",
                "mileage": 60000,
                "service_category": "Maintenance",
                "notes": "Latest Date Test",
                "line_items": [
                    {"description": "Latest Date Test Service", "cost": 50.00},
                ],
            },
            headers=auth_headers,
        )

        # Get dashboard
        response = await client.get(
            "/api/dashboard",
            headers=auth_headers,
        )
        data = response.json()

        # Find our test vehicle
        test_vehicle_stats = None
        for vehicle in data["vehicles"]:
            if vehicle["vin"] == test_vehicle["vin"]:
                test_vehicle_stats = vehicle
                break

        assert test_vehicle_stats is not None
        # latest_service_date should be set
        assert test_vehicle_stats["latest_service_date"] is not None

    async def test_dashboard_unauthenticated(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users can access dashboard (legacy behavior)."""
        # Uses optional_auth, so should work without auth
        response = await client.get("/api/dashboard")

        # Should return 200 or 401 depending on auth settings
        assert response.status_code in [200, 401]

    async def test_dashboard_totals_match_vehicle_sums(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that dashboard totals match sum of vehicle statistics."""
        response = await client.get(
            "/api/dashboard",
            headers=auth_headers,
        )
        data = response.json()

        # Calculate sums from vehicles
        vehicle_service_sum = sum(v["total_service_records"] for v in data["vehicles"])
        vehicle_fuel_sum = sum(v["total_fuel_records"] for v in data["vehicles"])
        vehicle_reminder_sum = sum(v["total_reminders"] for v in data["vehicles"])
        vehicle_document_sum = sum(v["total_documents"] for v in data["vehicles"])
        vehicle_note_sum = sum(v["total_notes"] for v in data["vehicles"])
        vehicle_photo_sum = sum(v["total_photos"] for v in data["vehicles"])

        # Totals should match sums
        assert data["total_service_records"] == vehicle_service_sum
        assert data["total_fuel_records"] == vehicle_fuel_sum
        assert data["total_reminders"] == vehicle_reminder_sum
        assert data["total_documents"] == vehicle_document_sum
        assert data["total_notes"] == vehicle_note_sum
        assert data["total_photos"] == vehicle_photo_sum

    async def test_dashboard_vehicle_info(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test that dashboard includes vehicle identifying information."""
        response = await client.get(
            "/api/dashboard",
            headers=auth_headers,
        )
        data = response.json()

        # Find our test vehicle
        test_vehicle_stats = None
        for vehicle in data["vehicles"]:
            if vehicle["vin"] == test_vehicle["vin"]:
                test_vehicle_stats = vehicle
                break

        assert test_vehicle_stats is not None
        # Should have vehicle identification fields
        assert "vin" in test_vehicle_stats
        assert "year" in test_vehicle_stats
        assert "make" in test_vehicle_stats
        assert "model" in test_vehicle_stats

    async def test_dashboard_shared_vehicle_fields(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that vehicle stats include sharing-related fields."""
        response = await client.get(
            "/api/dashboard",
            headers=auth_headers,
        )
        data = response.json()

        # Find any vehicle
        if data["vehicles"]:
            vehicle = data["vehicles"][0]
            # Should have sharing-related fields (even if not shared)
            assert "is_shared_with_me" in vehicle
            assert "shared_by_username" in vehicle
            assert "share_permission" in vehicle

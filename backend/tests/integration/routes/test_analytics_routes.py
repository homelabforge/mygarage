"""
Integration tests for analytics routes.

Tests vehicle analytics, garage analytics, vendor analytics,
seasonal analytics, and period comparison endpoints.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestVehicleAnalyticsRoutes:
    """Test per-vehicle analytics endpoints."""

    async def test_get_vehicle_analytics(self, client: AsyncClient, auth_headers, test_vehicle):
        """Vehicle analytics endpoint returns 200 with expected structure."""
        response = await client.get(
            f"/api/analytics/vehicles/{test_vehicle['vin']}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["vin"] == test_vehicle["vin"]
        assert "vehicle_name" in data
        assert "cost_analysis" in data
        assert "fuel_economy" in data
        assert "service_history" in data
        assert "predictions" in data

    async def test_get_vehicle_analytics_nonexistent_vin(self, client: AsyncClient, auth_headers):
        """Analytics for a nonexistent VIN returns 404."""
        response = await client.get(
            "/api/analytics/vehicles/00000000000000000",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_get_vehicle_analytics_unauthenticated(self, client: AsyncClient, test_vehicle):
        """Unauthenticated analytics request returns 401."""
        response = await client.get(
            f"/api/analytics/vehicles/{test_vehicle['vin']}",
        )

        assert response.status_code == 401

    async def test_get_vehicle_analytics_non_owner(
        self, client: AsyncClient, non_admin_headers, test_vehicle
    ):
        """Non-owner cannot access another user's vehicle analytics."""
        response = await client.get(
            f"/api/analytics/vehicles/{test_vehicle['vin']}",
            headers=non_admin_headers,
        )

        assert response.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
class TestGarageAnalyticsRoutes:
    """Test garage-level analytics endpoints."""

    async def test_get_garage_analytics(self, client: AsyncClient, auth_headers, test_vehicle):
        """Garage analytics returns 200 with expected structure."""
        response = await client.get(
            "/api/analytics/garage",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "total_costs" in data
        assert "cost_breakdown_by_category" in data
        assert "cost_by_vehicle" in data
        assert "monthly_trends" in data
        assert "vehicle_count" in data
        assert data["vehicle_count"] >= 1

    async def test_get_garage_analytics_unauthenticated(self, client: AsyncClient):
        """Unauthenticated garage analytics request returns 401."""
        response = await client.get("/api/analytics/garage")

        assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
class TestVendorAnalyticsRoutes:
    """Test vendor analytics endpoint."""

    async def test_get_vendor_analytics(self, client: AsyncClient, auth_headers, test_vehicle):
        """Vendor analytics returns 200 with expected structure."""
        response = await client.get(
            f"/api/analytics/vehicles/{test_vehicle['vin']}/vendors",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "vendors" in data
        assert "total_vendors" in data
        assert isinstance(data["vendors"], list)

    async def test_get_vendor_analytics_nonexistent_vin(self, client: AsyncClient, auth_headers):
        """Vendor analytics for a nonexistent VIN returns 404."""
        response = await client.get(
            "/api/analytics/vehicles/00000000000000000/vendors",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_get_vendor_analytics_non_owner(
        self, client: AsyncClient, non_admin_headers, test_vehicle
    ):
        """Non-owner cannot access vendor analytics for another user's vehicle."""
        response = await client.get(
            f"/api/analytics/vehicles/{test_vehicle['vin']}/vendors",
            headers=non_admin_headers,
        )

        assert response.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
class TestSeasonalAnalyticsRoutes:
    """Test seasonal analytics endpoint."""

    async def test_get_seasonal_analytics(self, client: AsyncClient, auth_headers, test_vehicle):
        """Seasonal analytics returns 200 with expected structure."""
        response = await client.get(
            f"/api/analytics/vehicles/{test_vehicle['vin']}/seasonal",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "seasons" in data
        assert isinstance(data["seasons"], list)

    async def test_get_seasonal_analytics_nonexistent_vin(self, client: AsyncClient, auth_headers):
        """Seasonal analytics for a nonexistent VIN returns 404."""
        response = await client.get(
            "/api/analytics/vehicles/00000000000000000/seasonal",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_get_seasonal_analytics_non_owner(
        self, client: AsyncClient, non_admin_headers, test_vehicle
    ):
        """Non-owner cannot access seasonal analytics for another user's vehicle."""
        response = await client.get(
            f"/api/analytics/vehicles/{test_vehicle['vin']}/seasonal",
            headers=non_admin_headers,
        )

        assert response.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
class TestPeriodComparisonRoutes:
    """Test period comparison endpoint."""

    async def test_compare_periods(self, client: AsyncClient, auth_headers, test_vehicle):
        """Period comparison returns 200 with expected structure."""
        params = {
            "period1_start": "2025-01-01",
            "period1_end": "2025-06-30",
            "period2_start": "2025-07-01",
            "period2_end": "2025-12-31",
        }
        response = await client.get(
            f"/api/analytics/vehicles/{test_vehicle['vin']}/compare",
            params=params,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "period1_label" in data
        assert "period2_label" in data
        assert "period1_total_cost" in data
        assert "period2_total_cost" in data
        assert "cost_change_amount" in data
        assert "category_changes" in data

    async def test_compare_periods_with_labels(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Period comparison with custom labels uses supplied labels."""
        params = {
            "period1_start": "2025-01-01",
            "period1_end": "2025-06-30",
            "period2_start": "2025-07-01",
            "period2_end": "2025-12-31",
            "period1_label": "H1 2025",
            "period2_label": "H2 2025",
        }
        response = await client.get(
            f"/api/analytics/vehicles/{test_vehicle['vin']}/compare",
            params=params,
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["period1_label"] == "H1 2025"
        assert data["period2_label"] == "H2 2025"

    async def test_compare_periods_nonexistent_vin(self, client: AsyncClient, auth_headers):
        """Period comparison for a nonexistent VIN returns 404."""
        params = {
            "period1_start": "2025-01-01",
            "period1_end": "2025-06-30",
            "period2_start": "2025-07-01",
            "period2_end": "2025-12-31",
        }
        response = await client.get(
            "/api/analytics/vehicles/00000000000000000/compare",
            params=params,
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_compare_periods_missing_params(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Period comparison without required date params returns 422."""
        response = await client.get(
            f"/api/analytics/vehicles/{test_vehicle['vin']}/compare",
            headers=auth_headers,
        )

        assert response.status_code == 422

    async def test_compare_periods_non_owner(
        self, client: AsyncClient, non_admin_headers, test_vehicle
    ):
        """Non-owner cannot compare periods for another user's vehicle."""
        params = {
            "period1_start": "2025-01-01",
            "period1_end": "2025-06-30",
            "period2_start": "2025-07-01",
            "period2_end": "2025-12-31",
        }
        response = await client.get(
            f"/api/analytics/vehicles/{test_vehicle['vin']}/compare",
            params=params,
            headers=non_admin_headers,
        )

        assert response.status_code == 403

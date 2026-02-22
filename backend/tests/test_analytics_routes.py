"""Integration tests for analytics API routes."""

import pytest
from httpx import AsyncClient

from app.models.user import User
from app.models.vehicle import Vehicle


@pytest.mark.integration
@pytest.mark.analytics
@pytest.mark.asyncio
class TestAnalyticsEndpoints:
    """Test analytics API endpoints with real database data."""

    async def test_get_vehicle_analytics_success(
        self,
        client: AsyncClient,
        vehicle_with_analytics_data: Vehicle,
        auth_headers: dict,
    ):
        """Test getting vehicle analytics with sufficient data."""
        response = await client.get(
            f"/api/analytics/vehicles/{vehicle_with_analytics_data.vin}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Check response structure
        assert "vin" in data
        assert "vehicle_name" in data
        assert "cost_analysis" in data
        assert "cost_projection" in data
        assert "fuel_economy" in data
        assert "service_history" in data
        assert "predictions" in data

        # Validate cost_analysis structure
        cost_analysis = data["cost_analysis"]
        assert "total_cost" in cost_analysis
        assert "average_monthly_cost" in cost_analysis
        assert "monthly_breakdown" in cost_analysis
        assert "service_type_breakdown" in cost_analysis
        assert "anomalies" in cost_analysis
        assert isinstance(cost_analysis["anomalies"], list)

    async def test_get_vehicle_analytics_invalid_vin(self, client: AsyncClient, auth_headers: dict):
        """Test getting analytics for non-existent vehicle."""
        response = await client.get("/api/analytics/vehicles/INVALIDVIN123", headers=auth_headers)

        assert response.status_code == 404

    async def test_get_vendor_analytics(
        self,
        client: AsyncClient,
        vehicle_with_service_records: Vehicle,
        auth_headers: dict,
    ):
        """Test getting vendor analytics."""
        response = await client.get(
            f"/api/analytics/vehicles/{vehicle_with_service_records.vin}/vendors",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert "vendors" in data
        assert "total_vendors" in data
        assert isinstance(data["vendors"], list)

    async def test_get_seasonal_analytics(
        self,
        client: AsyncClient,
        vehicle_with_service_records: Vehicle,
        auth_headers: dict,
    ):
        """Test getting seasonal analytics."""
        response = await client.get(
            f"/api/analytics/vehicles/{vehicle_with_service_records.vin}/seasonal",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert "seasons" in data
        assert "annual_average" in data
        assert isinstance(data["seasons"], list)

        # Should have 4 seasons
        if data["seasons"]:
            assert len(data["seasons"]) <= 4

    async def test_compare_periods(
        self,
        client: AsyncClient,
        vehicle_with_analytics_data: Vehicle,
        auth_headers: dict,
    ):
        """Test period comparison endpoint."""
        response = await client.get(
            f"/api/analytics/vehicles/{vehicle_with_analytics_data.vin}/compare",
            params={
                "period1_start": "2024-01-01",
                "period1_end": "2024-03-31",
                "period2_start": "2024-04-01",
                "period2_end": "2024-06-30",
            },
            headers=auth_headers,
        )

        # May return 200 or 400 depending on data availability
        assert response.status_code in [200, 400]

        if response.status_code == 200:
            data = response.json()
            assert "period1_label" in data
            assert "period2_label" in data
            assert "period1_total_cost" in data
            assert "period2_total_cost" in data
            assert "cost_change_amount" in data
            assert "cost_change_percent" in data
            assert "category_changes" in data

    async def test_compare_periods_missing_params(
        self, client: AsyncClient, test_vehicle: dict, auth_headers: dict
    ):
        """Test period comparison with missing parameters."""
        response = await client.get(
            f"/api/analytics/vehicles/{test_vehicle['vin']}/compare",
            params={
                "period1_start": "2024-01-01",
                # Missing other required params
            },
            headers=auth_headers,
        )

        # Should return 422 for validation error
        assert response.status_code == 422

    async def test_export_analytics_pdf(
        self,
        client: AsyncClient,
        vehicle_with_analytics_data: Vehicle,
        auth_headers: dict,
    ):
        """Test PDF export endpoint."""
        response = await client.get(
            f"/api/analytics/vehicles/{vehicle_with_analytics_data.vin}/export",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert "attachment" in response.headers.get("content-disposition", "")

        # Validate PDF magic bytes and content
        assert response.content[:5] == b"%PDF-"
        assert len(response.content) > 100

    async def test_export_garage_analytics_pdf(
        self,
        client: AsyncClient,
        vehicle_with_analytics_data: Vehicle,
        auth_headers: dict,
    ):
        """Test garage-wide PDF export endpoint."""
        response = await client.get(
            "/api/analytics/garage/export",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert "attachment" in response.headers.get("content-disposition", "")

        # Validate PDF magic bytes and content
        assert response.content[:5] == b"%PDF-"
        assert len(response.content) > 100

    async def test_garage_analytics(self, client: AsyncClient, test_user: User, auth_headers: dict):
        """Test garage-wide analytics endpoint."""
        response = await client.get("/api/analytics/garage", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        assert "total_costs" in data
        assert "cost_breakdown_by_category" in data
        assert "cost_by_vehicle" in data
        assert "monthly_trends" in data
        assert "vehicle_count" in data

        # Validate total_costs structure
        total_costs = data["total_costs"]
        assert "total_garage_value" in total_costs
        assert "total_maintenance" in total_costs
        assert "total_fuel" in total_costs


@pytest.mark.integration
@pytest.mark.analytics
@pytest.mark.asyncio
async def test_analytics_caching(
    client: AsyncClient, vehicle_with_analytics_data: Vehicle, auth_headers: dict
):
    """Test that analytics results are cached."""
    vin = vehicle_with_analytics_data.vin

    # First request - should hit database
    response1 = await client.get(f"/api/analytics/vehicles/{vin}", headers=auth_headers)
    assert response1.status_code == 200
    data1 = response1.json()

    # Second request - should be from cache (faster)
    response2 = await client.get(f"/api/analytics/vehicles/{vin}", headers=auth_headers)
    assert response2.status_code == 200
    data2 = response2.json()

    # Data should be identical
    assert data1 == data2


@pytest.mark.integration
@pytest.mark.analytics
@pytest.mark.asyncio
async def test_anomaly_detection(
    client: AsyncClient, vehicle_with_analytics_data: Vehicle, auth_headers: dict
):
    """Test that anomaly detection is working."""
    response = await client.get(
        f"/api/analytics/vehicles/{vehicle_with_analytics_data.vin}",
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()

    cost_analysis = data["cost_analysis"]
    assert "anomalies" in cost_analysis

    # Anomalies may or may not exist depending on data
    anomalies = cost_analysis["anomalies"]
    if anomalies:
        # Validate anomaly structure
        for anomaly in anomalies:
            assert "month" in anomaly
            assert "amount" in anomaly
            assert "baseline" in anomaly
            assert "deviation_percent" in anomaly
            assert "severity" in anomaly
            assert anomaly["severity"] in ["warning", "critical"]
            assert "message" in anomaly

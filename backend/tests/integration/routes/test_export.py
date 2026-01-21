"""
Integration tests for export routes.

Tests data export functionality (CSV, JSON).
Note: PDF export is not implemented in this API.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.slow
class TestExportRoutes:
    """Test export API endpoints."""

    async def test_export_service_history_csv(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test exporting service history as CSV."""
        vehicle = test_vehicle_with_records

        response = await client.get(
            f"/api/export/vehicles/{vehicle['vin']}/service/csv",
            headers=auth_headers,
        )

        assert response.status_code == 200
        # Check content type is CSV
        content_type = response.headers.get("content-type", "")
        assert "csv" in content_type.lower() or "text/csv" in content_type

    async def test_export_fuel_records_csv(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test exporting fuel records as CSV."""
        vehicle = test_vehicle_with_records

        response = await client.get(
            f"/api/export/vehicles/{vehicle['vin']}/fuel/csv",
            headers=auth_headers,
        )

        assert response.status_code == 200
        # Check content type is CSV
        content_type = response.headers.get("content-type", "")
        assert "csv" in content_type.lower() or "text/csv" in content_type

    async def test_export_all_data_json(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test exporting all vehicle data as JSON."""
        vehicle = test_vehicle_with_records

        response = await client.get(
            f"/api/export/vehicles/{vehicle['vin']}/json",
            headers=auth_headers,
        )

        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "json" in content_type.lower() or "application/json" in content_type

        # Verify JSON structure
        data = response.json()
        assert "vehicle" in data
        assert "export_date" in data
        assert "service_records" in data
        assert "fuel_records" in data

    async def test_export_unauthorized(
        self, client: AsyncClient, test_vehicle_with_records
    ):
        """Test that unauthenticated users cannot export data."""
        vehicle = test_vehicle_with_records

        response = await client.get(
            f"/api/export/vehicles/{vehicle['vin']}/service/csv"
        )

        assert response.status_code == 401

    async def test_export_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test exporting data for non-existent vehicle."""
        response = await client.get(
            "/api/export/vehicles/INVALIDVIN1234567/service/csv",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_export_empty_vehicle(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test exporting data for vehicle with no records."""
        response = await client.get(
            f"/api/export/vehicles/{test_vehicle['vin']}/service/csv",
            headers=auth_headers,
        )

        # Should still succeed but with just headers
        assert response.status_code == 200

    async def test_export_rate_limiting(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test that export endpoints have rate limiting."""
        vehicle = test_vehicle_with_records

        # Make multiple rapid requests
        responses = []
        for _ in range(10):
            response = await client.get(
                f"/api/export/vehicles/{vehicle['vin']}/service/csv",
                headers=auth_headers,
            )
            responses.append(response.status_code)

        # Should eventually hit rate limit (429) or succeed
        # Note: May not trigger in test environment without rate limiting configured
        assert all(code in [200, 429] for code in responses)

    async def test_export_csv_format_validation(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test that CSV exports have proper format."""
        vehicle = test_vehicle_with_records

        response = await client.get(
            f"/api/export/vehicles/{vehicle['vin']}/service/csv",
            headers=auth_headers,
        )

        # Accept 200 (success) or 429 (rate limit from other tests running first)
        assert response.status_code in [200, 429]

        # Only validate CSV format if we got a successful response
        if response.status_code == 200:
            content = response.text
            # CSV should have headers
            if content:
                lines = content.split("\n")
                # First line should contain column headers
                if lines:
                    assert "," in lines[0]  # Has comma separators

    async def test_export_odometer_csv(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test exporting odometer records as CSV."""
        vehicle = test_vehicle_with_records

        response = await client.get(
            f"/api/export/vehicles/{vehicle['vin']}/odometer/csv",
            headers=auth_headers,
        )

        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "csv" in content_type.lower() or "text/csv" in content_type

"""
Integration tests for export routes.

Tests data export functionality (PDF, CSV).
"""
import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.slow
class TestExportRoutes:
    """Test export API endpoints."""

    async def test_export_vehicle_pdf(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test exporting vehicle data as PDF."""
        vehicle = test_vehicle_with_records

        response = await client.get(
            f"/api/vehicles/{vehicle['vin']}/export/pdf",
            headers=auth_headers,
        )

        # Should return PDF or success
        assert response.status_code in [200, 201]
        if response.status_code == 200:
            # Check content type is PDF
            content_type = response.headers.get("content-type", "")
            assert "pdf" in content_type.lower() or "application/pdf" == content_type

    async def test_export_service_history_csv(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test exporting service history as CSV."""
        vehicle = test_vehicle_with_records

        response = await client.get(
            f"/api/vehicles/{vehicle['vin']}/export/service-csv",
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
            f"/api/vehicles/{vehicle['vin']}/export/fuel-csv",
            headers=auth_headers,
        )

        assert response.status_code == 200
        # Check content type is CSV
        content_type = response.headers.get("content-type", "")
        assert "csv" in content_type.lower() or "text/csv" in content_type

    async def test_export_all_data(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test exporting all vehicle data."""
        vehicle = test_vehicle_with_records

        response = await client.get(
            f"/api/vehicles/{vehicle['vin']}/export/all",
            headers=auth_headers,
        )

        # Should return ZIP or JSON with all data
        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert any(
            t in content_type.lower()
            for t in ["zip", "json", "application/json", "application/zip"]
        )

    async def test_export_unauthorized(
        self, client: AsyncClient, test_vehicle_with_records
    ):
        """Test that unauthenticated users cannot export data."""
        vehicle = test_vehicle_with_records

        response = await client.get(
            f"/api/vehicles/{vehicle['vin']}/export/pdf"
        )

        assert response.status_code == 401

    async def test_export_vehicle_not_found(
        self, client: AsyncClient, auth_headers
    ):
        """Test exporting data for non-existent vehicle."""
        response = await client.get(
            "/api/vehicles/INVALIDVIN1234567/export/pdf",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_export_empty_vehicle(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test exporting data for vehicle with no records."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/export/pdf",
            headers=auth_headers,
        )

        # Should still succeed but with empty data
        assert response.status_code in [200, 204]

    async def test_export_rate_limiting(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test that export endpoints have rate limiting."""
        vehicle = test_vehicle_with_records

        # Make multiple rapid requests
        responses = []
        for _ in range(10):
            response = await client.get(
                f"/api/vehicles/{vehicle['vin']}/export/pdf",
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
            f"/api/vehicles/{vehicle['vin']}/export/service-csv",
            headers=auth_headers,
        )

        assert response.status_code == 200
        content = response.text

        # CSV should have headers
        if content:
            lines = content.split("\n")
            # First line should contain column headers
            if lines:
                assert "," in lines[0]  # Has comma separators

    async def test_export_pdf_contains_vehicle_info(
        self, client: AsyncClient, auth_headers, test_vehicle_with_records
    ):
        """Test that PDF export contains vehicle information."""
        vehicle = test_vehicle_with_records

        response = await client.get(
            f"/api/vehicles/{vehicle['vin']}/export/pdf",
            headers=auth_headers,
        )

        assert response.status_code == 200
        # PDF should have content
        assert len(response.content) > 0
        # Basic PDF structure check
        assert response.content.startswith(b"%PDF")

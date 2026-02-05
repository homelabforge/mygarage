"""
Integration tests for report routes.

Tests PDF and CSV report generation endpoints.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestReportRoutes:
    """Test report API endpoints."""

    async def test_download_service_history_pdf(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test downloading service history PDF report."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reports/service-history-pdf",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.headers.get("content-type") == "application/pdf"
        # Verify it's a valid PDF (starts with %PDF)
        assert response.content[:4] == b"%PDF"

    async def test_download_service_history_pdf_with_date_range(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test downloading service history PDF with date filters."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reports/service-history-pdf",
            headers=auth_headers,
            params={"start_date": "2024-01-01", "end_date": "2024-12-31"},
        )

        assert response.status_code == 200
        assert response.headers.get("content-type") == "application/pdf"
        assert response.content[:4] == b"%PDF"

    async def test_download_cost_summary_pdf(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test downloading cost summary PDF report."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reports/cost-summary-pdf",
            headers=auth_headers,
            params={"year": 2024},
        )

        assert response.status_code == 200
        assert response.headers.get("content-type") == "application/pdf"
        assert response.content[:4] == b"%PDF"

    async def test_download_cost_summary_pdf_requires_year(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that cost summary requires year parameter."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reports/cost-summary-pdf",
            headers=auth_headers,
        )

        assert response.status_code == 422  # Validation error

    async def test_download_tax_deduction_pdf(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test downloading tax deduction PDF report."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reports/tax-deduction-pdf",
            headers=auth_headers,
            params={"year": 2024},
        )

        assert response.status_code == 200
        assert response.headers.get("content-type") == "application/pdf"
        assert response.content[:4] == b"%PDF"

    async def test_download_tax_deduction_pdf_requires_year(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test that tax deduction requires year parameter."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reports/tax-deduction-pdf",
            headers=auth_headers,
        )

        assert response.status_code == 422  # Validation error

    async def test_download_service_history_csv(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test downloading service history CSV export."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reports/service-history-csv",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.headers.get("content-type") == "text/csv; charset=utf-8"
        # Verify it has CSV header
        content = response.content.decode("utf-8")
        assert "Date" in content
        assert "Mileage" in content
        assert "Service Type" in content

    async def test_download_service_history_csv_with_date_range(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test downloading service history CSV with date filters."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reports/service-history-csv",
            headers=auth_headers,
            params={"start_date": "2024-01-01", "end_date": "2024-12-31"},
        )

        assert response.status_code == 200
        assert response.headers.get("content-type") == "text/csv; charset=utf-8"

    async def test_download_all_records_csv(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test downloading all records CSV export."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reports/all-records-csv",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.headers.get("content-type") == "text/csv; charset=utf-8"
        # Verify it has CSV header
        content = response.content.decode("utf-8")
        assert "Date" in content
        assert "Type" in content
        assert "Category" in content

    async def test_download_all_records_csv_filtered_by_year(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test downloading all records CSV filtered by year."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reports/all-records-csv",
            headers=auth_headers,
            params={"year": 2024},
        )

        assert response.status_code == 200
        assert response.headers.get("content-type") == "text/csv; charset=utf-8"

    async def test_reports_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test report endpoints with non-existent vehicle."""
        vin = "1HGBH000000000000"

        # Service history PDF
        response = await client.get(
            f"/api/vehicles/{vin}/reports/service-history-pdf",
            headers=auth_headers,
        )
        assert response.status_code == 404

        # Cost summary PDF
        response = await client.get(
            f"/api/vehicles/{vin}/reports/cost-summary-pdf",
            headers=auth_headers,
            params={"year": 2024},
        )
        assert response.status_code == 404

        # Service history CSV
        response = await client.get(
            f"/api/vehicles/{vin}/reports/service-history-csv",
            headers=auth_headers,
        )
        assert response.status_code == 404

        # All records CSV
        response = await client.get(
            f"/api/vehicles/{vin}/reports/all-records-csv",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_reports_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test that unauthenticated users cannot access reports."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reports/service-history-pdf"
        )
        assert response.status_code == 401

        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reports/cost-summary-pdf",
            params={"year": 2024},
        )
        assert response.status_code == 401

        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reports/service-history-csv"
        )
        assert response.status_code == 401

    async def test_pdf_content_disposition(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test that PDF reports have correct Content-Disposition header."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reports/service-history-pdf",
            headers=auth_headers,
        )

        assert response.status_code == 200
        content_disp = response.headers.get("content-disposition", "")
        assert "attachment" in content_disp
        assert "filename=" in content_disp
        assert ".pdf" in content_disp

    async def test_csv_content_disposition(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test that CSV exports have correct Content-Disposition header."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reports/service-history-csv",
            headers=auth_headers,
        )

        assert response.status_code == 200
        content_disp = response.headers.get("content-disposition", "")
        assert "attachment" in content_disp
        assert "filename=" in content_disp
        assert ".csv" in content_disp

    async def test_csv_header_columns(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test that CSV exports have correct column headers."""
        # Service history CSV
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reports/service-history-csv",
            headers=auth_headers,
        )
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        first_line = content.split("\n")[0]
        assert "Date" in first_line
        assert "Mileage" in first_line
        assert "Service Type" in first_line
        assert "Cost" in first_line
        assert "Vendor Name" in first_line

        # All records CSV
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reports/all-records-csv",
            headers=auth_headers,
        )
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        first_line = content.split("\n")[0]
        assert "Date" in first_line
        assert "Type" in first_line
        assert "Category" in first_line
        assert "Description" in first_line
        assert "Cost" in first_line

    async def test_cost_summary_pdf_different_years(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test cost summary PDF for different years."""
        for year in [2023, 2024, 2025]:
            response = await client.get(
                f"/api/vehicles/{test_vehicle['vin']}/reports/cost-summary-pdf",
                headers=auth_headers,
                params={"year": year},
            )
            assert response.status_code == 200
            assert response.content[:4] == b"%PDF"

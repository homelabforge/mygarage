"""
Integration tests for report routes.

Tests PDF and CSV report generation endpoints.

The two CSV reports emit v6 unit tokens in the caller's units (issue #152
phase 2b task 5), so their distance and volume headers depend on who asked.
The assertions here cover the shape both spellings share; which spelling a
given caller gets is pinned against controlled accounts in
`test_reports_csv_v6_units.py`.
"""

import pytest
from httpx import AsyncClient

# Hand-written: the complete ordered header row each report can emit.
SERVICE_HISTORY_HEADERS = {
    "Date,Odometer (km),Category,Description,Cost,Vendor,Notes",
    "Date,Odometer (mi),Category,Description,Cost,Vendor,Notes",
}
ALL_RECORDS_HEADERS = {
    f"Date,Type,Category,Description,Cost,Odometer ({distance}),Vendor,Volume ({volume})"
    for distance in ("km", "mi")
    for volume in ("L", "gal_us", "gal_uk")
}


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
        content = response.content.decode("utf-8")
        assert content.split("\r\n")[0] in SERVICE_HISTORY_HEADERS

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
        content = response.content.decode("utf-8")
        assert content.split("\r\n")[0] in ALL_RECORDS_HEADERS

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
        """Both reports emit one complete, ordered, v6 header row.

        The old form of this test looked for a handful of names ANYWHERE in
        the first line, which cannot see a column landing in the wrong place,
        an extra column, or a missing one. Comparing the whole row can.
        """
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reports/service-history-csv",
            headers=auth_headers,
        )
        assert response.status_code == 200
        first_line = response.content.decode("utf-8").split("\r\n")[0]
        assert first_line in SERVICE_HISTORY_HEADERS
        assert "Mileage" not in first_line

        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reports/all-records-csv",
            headers=auth_headers,
        )
        assert response.status_code == 200
        first_line = response.content.decode("utf-8").split("\r\n")[0]
        assert first_line in ALL_RECORDS_HEADERS

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

    async def test_reports_forbidden_non_owner(
        self, client: AsyncClient, non_admin_headers, test_vehicle
    ):
        """Test that non-owner users cannot access another user's reports."""
        vin = test_vehicle["vin"]
        response = await client.get(
            f"/api/vehicles/{vin}/reports/service-history-csv",
            headers=non_admin_headers,
        )
        assert response.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
class TestSaleHistoryPrivacy:
    """The buyer-facing PDF must contain only what its header promises.

    Asserting on raw response bytes would be a test that cannot fail: ReportLab
    writes text into compressed content streams, so a plain substring check
    passes whether or not the string was rendered. Text is extracted with fitz,
    the same way tests/unit/utils/test_pdf_generator.py does it.
    """

    async def test_notes_never_reach_the_sale_pdf(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        from datetime import date

        import fitz

        from app.models.service_visit import ServiceVisit
        from app.models.vehicle import Vehicle

        vin = "SALEPDFPRIV000001"
        db_session.add(
            Vehicle(
                vin=vin,
                user_id=test_user["id"],
                nickname="For Sale",
                vehicle_type="Car",
                year=2020,
                make="Test",
                model="Sale",
                license_plate="ABC-1234",
            )
        )
        await db_session.commit()

        # A visit with NO line items: the branch that used to fall back to notes.
        db_session.add(
            ServiceVisit(
                vin=vin,
                date=date(2026, 1, 15),
                service_category="Maintenance",
                notes="Paid $850 cash at Joe's Garage, plate ABC-1234, claim #55",
            )
        )
        await db_session.commit()

        response = await client.get(
            f"/api/vehicles/{vin}/reports/sale-history-pdf", headers=auth_headers
        )
        assert response.status_code == 200
        assert response.content[:4] == b"%PDF"

        with fitz.open(stream=response.content, filetype="pdf") as doc:
            text = "".join(page.get_text() for page in doc)

        # The header promises costs, vendors and plates are omitted.
        assert "850" not in text
        assert "Joe's Garage" not in text
        assert "ABC-1234" not in text
        assert "claim #55" not in text
        # The service still appears, by category.
        assert "Maintenance" in text

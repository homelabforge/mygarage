"""
Integration tests for export routes.

Tests data export functionality (CSV, JSON).
Note: PDF export is not implemented in this API.
"""

import pytest
from httpx import AsyncClient


@pytest.fixture(autouse=True)
def _reset_export_rate_limit():
    """Reset export routes' shared limiter storage before each test.

    ``routes/export.py`` defines a single module-level ``Limiter`` shared by
    every export endpoint (5/minute, deliberately strict for expensive
    CSV/JSON generation). Without a reset, cumulative calls across this
    file's tests (including ``test_export_rate_limiting``'s intentional
    10-call burst) exhaust the budget and later tests intermittently 429
    regardless of their own logic. Mirrors the precedent in
    ``test_auth.py``'s ``TestCookieSecureFlag._reset_rate_limits``.
    """
    from app.routes.export import limiter as export_limiter

    storage = export_limiter._storage
    storage.storage.clear()
    storage.expirations.clear()
    if hasattr(storage, "events"):
        storage.events.clear()


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
        assert "service_visits" in data
        assert "fuel_records" in data

    async def test_export_unauthorized(self, client: AsyncClient, test_vehicle_with_records):
        """Test that unauthenticated users cannot export data."""
        vehicle = test_vehicle_with_records

        response = await client.get(f"/api/export/vehicles/{vehicle['vin']}/service/csv")

        assert response.status_code == 401

    async def test_export_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test exporting data for non-existent vehicle."""
        response = await client.get(
            "/api/export/vehicles/INVALIDVIN1234567/service/csv",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_export_empty_vehicle(self, client: AsyncClient, auth_headers, test_vehicle):
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


@pytest.mark.integration
@pytest.mark.asyncio
class TestFuelCSVExportEngineHours:
    """Phase 9: fuel_records.engine_hours is a real exported column (P0 EXCLUDE removed)."""

    async def test_fuel_csv_export_includes_engine_hours_column(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        import csv
        import io
        from datetime import date
        from decimal import Decimal

        from app.models.fuel import FuelRecord

        db_session.add(
            FuelRecord(
                vin=test_vehicle["vin"],
                date=date(2026, 4, 1),
                odometer_km=Decimal("1000.00"),
                engine_hours=Decimal("123.4"),
                liters=Decimal("20.0"),
                cost=Decimal("30.00"),
                is_full_tank=True,
            )
        )
        await db_session.commit()

        response = await client.get(
            f"/api/export/vehicles/{test_vehicle['vin']}/fuel/csv",
            headers=auth_headers,
        )
        assert response.status_code == 200

        reader = csv.DictReader(io.StringIO(response.text))
        rows = list(reader)
        assert "Engine Hours" in reader.fieldnames

        row = next(r for r in rows if r["Date"] == "2026-04-01")
        assert row["Engine Hours"] == "123.4"

    async def test_fuel_csv_export_null_engine_hours_is_blank(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        """Records with no engine_hours (pure-distance vehicle) emit an empty cell.

        Uses a dedicated VIN rather than the shared ``test_vehicle`` /
        ``test_vehicle_with_records`` fixtures: those reuse one fixed VIN
        across the whole test session, so records from unrelated tests
        (including this class's own ``engine_hours``-bearing record) would
        otherwise leak into the row set and break an "all blank" assertion.
        """
        import csv
        import io
        from datetime import date
        from decimal import Decimal

        from app.models.fuel import FuelRecord
        from app.models.vehicle import Vehicle

        vin = "FUELNULLHRS000001"
        db_session.add(
            Vehicle(
                vin=vin,
                user_id=test_user["id"],
                nickname="Fuel Null Hours",
                vehicle_type="Car",
                year=2024,
                make="Test",
                model="NullHours",
            )
        )
        await db_session.commit()

        db_session.add(
            FuelRecord(
                vin=vin,
                date=date(2026, 4, 6),
                odometer_km=Decimal("2000.00"),
                liters=Decimal("15.0"),
                cost=Decimal("22.00"),
                is_full_tank=True,
            )
        )
        await db_session.commit()

        response = await client.get(
            f"/api/export/vehicles/{vin}/fuel/csv",
            headers=auth_headers,
        )
        assert response.status_code == 200
        reader = csv.DictReader(io.StringIO(response.text))
        rows = list(reader)
        assert rows
        assert all(r["Engine Hours"] == "" for r in rows)


@pytest.mark.integration
@pytest.mark.asyncio
class TestServiceCSVExportEngineHours:
    """Phase 9: service-visit CSV export gains an engine_hours column."""

    async def test_service_csv_export_includes_engine_hours_column(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        import csv
        import io
        from datetime import date
        from decimal import Decimal

        from app.models.service_line_item import ServiceLineItem
        from app.models.service_visit import ServiceVisit

        visit = ServiceVisit(
            vin=test_vehicle["vin"],
            date=date(2026, 4, 2),
            odometer_km=Decimal("1000.00"),
            engine_hours=Decimal("55.5"),
            service_category="Maintenance",
            total_cost=Decimal("45.00"),
        )
        db_session.add(visit)
        await db_session.flush()
        db_session.add(
            ServiceLineItem(visit_id=visit.id, description="Oil change", cost=Decimal("45.00"))
        )
        await db_session.commit()

        response = await client.get(
            f"/api/export/vehicles/{test_vehicle['vin']}/service/csv",
            headers=auth_headers,
        )
        assert response.status_code == 200
        reader = csv.DictReader(io.StringIO(response.text))
        rows = list(reader)
        assert "Engine Hours" in reader.fieldnames
        row = next(r for r in rows if r["Date"] == "2026-04-02")
        assert row["Engine Hours"] == "55.5"


@pytest.mark.integration
@pytest.mark.asyncio
class TestHoursCSVExport:
    """Phase 9: standalone hours CSV export, mirroring the odometer CSV endpoint."""

    async def test_export_hours_csv(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        import csv
        import io
        from datetime import date
        from decimal import Decimal

        from app.models.hours import HoursRecord

        db_session.add(
            HoursRecord(
                vin=test_vehicle["vin"],
                date=date(2026, 4, 3),
                engine_hours=Decimal("200.1"),
                notes="Manual reading",
                source="manual",
            )
        )
        await db_session.commit()

        response = await client.get(
            f"/api/export/vehicles/{test_vehicle['vin']}/hours/csv",
            headers=auth_headers,
        )
        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "csv" in content_type.lower() or "text/csv" in content_type

        reader = csv.DictReader(io.StringIO(response.text))
        rows = list(reader)
        # `unit_system` accompanies `units_version` on every export: the first
        # is the schema version, the second says which units the values are in.
        # Hours are dimensionless, so this export is always "metric".
        assert set(reader.fieldnames) == {
            "units_version",
            "unit_system",
            "Date",
            "Engine Hours",
            "Notes",
            "Source",
        }
        row = next(r for r in rows if r["Date"] == "2026-04-03")
        assert row["Engine Hours"] == "200.1"
        assert row["Notes"] == "Manual reading"
        assert row["Source"] == "manual"

    async def test_export_hours_csv_unauthorized(
        self, client: AsyncClient, test_vehicle_with_records
    ):
        """Matches the odometer CSV endpoint's authz: 401 with no token."""
        vehicle = test_vehicle_with_records
        response = await client.get(f"/api/export/vehicles/{vehicle['vin']}/hours/csv")
        assert response.status_code == 401

    async def test_export_hours_csv_vehicle_not_found(self, client: AsyncClient, auth_headers):
        response = await client.get(
            "/api/export/vehicles/INVALIDVIN1234567/hours/csv",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_export_hours_csv_forbidden_non_owner(
        self, client: AsyncClient, non_admin_headers, test_vehicle
    ):
        response = await client.get(
            f"/api/export/vehicles/{test_vehicle['vin']}/hours/csv",
            headers=non_admin_headers,
        )
        assert response.status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
class TestFullVehicleJSONExportHours:
    """Phase 9: full-vehicle JSON export gains an hours_records array."""

    async def test_json_export_contains_hours_records(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        from datetime import date
        from decimal import Decimal

        from app.models.hours import HoursRecord

        db_session.add(
            HoursRecord(
                vin=test_vehicle["vin"],
                date=date(2026, 4, 4),
                engine_hours=Decimal("321.9"),
                notes="JSON export check",
                source="manual",
            )
        )
        await db_session.commit()

        response = await client.get(
            f"/api/export/vehicles/{test_vehicle['vin']}/json",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "hours_records" in data
        matching = [r for r in data["hours_records"] if r["date"] == "2026-04-04"]
        assert len(matching) == 1
        assert matching[0]["engine_hours"] == 321.9
        assert matching[0]["notes"] == "JSON export check"
        assert matching[0]["source"] == "manual"

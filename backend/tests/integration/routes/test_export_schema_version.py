"""Pins the #152 Task 1 split of the shared export schema-version constant.

Before this task, `EXPORT_SCHEMA_VERSION = "5"` was written into both the CSV
`units_version` cell (every data row, `generate_csv_stream`) and the JSON
backup's top-level `"export_version"` field. Bumping it for the CSV surface
(unit-preference-aware headers land in later tasks of this phase) would have
silently moved the JSON backup contract too, since both endpoints read one
name. This module proves the fix: `CSV_SCHEMA_VERSION = "6"` and
`JSON_SCHEMA_VERSION = "5"` are independent, `EXPORT_SCHEMA_VERSION` is gone,
and the five dimensionless CSV pairs (hours, warranties, insurance, tax,
notes -- the ones that call `generate_csv_stream` directly rather than going
through `build_csv`) change ONLY in the version cell.

Every expected value below is a hand-written literal, never read back from
`app.routes.export.CSV_SCHEMA_VERSION` / `JSON_SCHEMA_VERSION`: both sides of
an assertion tracing to one definition would prove nothing (this project's
most common test defect, per the phase brief).

Each test uses a dedicated VIN rather than the shared `test_vehicle` /
`test_vehicle_with_records` fixtures, so a record from an unrelated test
sharing the fixed session VIN can't leak into a single-row assertion (see
`TestFuelCSVExportEngineHours` in test_export.py for the precedent).
"""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _make_vehicle(db_session, test_user, vin: str, model: str) -> None:
    from app.models.vehicle import Vehicle

    db_session.add(
        Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname=f"Schema Version {model}",
            vehicle_type="Car",
            year=2024,
            make="Test",
            model=model,
        )
    )
    await db_session.commit()


class TestDimensionlessCSVPairsVersionCellOnly:
    """The five `generate_csv_stream`-direct pairs: only the version cell moves.

    Each test seeds exactly one row with every exportable field populated,
    then asserts the full header set AND every data cell by hand-written
    literal, plus `units_version == "6"`. If the constant split had touched
    anything besides that one cell, one of the non-version assertions would
    fail.
    """

    async def test_hours_csv_unchanged_except_version_cell(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        from app.models.hours import HoursRecord

        vin = "SCHVERHOURS000001"
        await _make_vehicle(db_session, test_user, vin, "HoursSchemaVer")
        db_session.add(
            HoursRecord(
                vin=vin,
                date=date(2026, 5, 1),
                engine_hours=Decimal("42.0"),
                notes="v6 pin",
                source="manual",
            )
        )
        await db_session.commit()

        response = await client.get(f"/api/export/vehicles/{vin}/hours/csv", headers=auth_headers)
        assert response.status_code == 200, response.text

        reader = csv.DictReader(io.StringIO(response.text))
        rows = list(reader)
        assert set(reader.fieldnames) == {
            "units_version",
            "unit_system",
            "Date",
            "Engine Hours",
            "Notes",
            "Source",
        }
        assert len(rows) == 1
        row = rows[0]
        assert row["units_version"] == "6"
        assert row["unit_system"] == "metric"
        assert row["Date"] == "2026-05-01"
        assert row["Engine Hours"] == "42.0"
        assert row["Notes"] == "v6 pin"
        assert row["Source"] == "manual"

    async def test_tax_csv_unchanged_except_version_cell(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        from app.models.tax import TaxRecord

        vin = "SCHVERTAX0000001"
        await _make_vehicle(db_session, test_user, vin, "TaxSchemaVer")
        db_session.add(
            TaxRecord(
                vin=vin,
                date=date(2026, 5, 2),
                tax_type="Registration",
                amount=Decimal("120.50"),
                renewal_date=date(2027, 5, 2),
                notes="Annual renewal",
            )
        )
        await db_session.commit()

        response = await client.get(f"/api/export/vehicles/{vin}/tax/csv", headers=auth_headers)
        assert response.status_code == 200, response.text

        reader = csv.DictReader(io.StringIO(response.text))
        rows = list(reader)
        assert set(reader.fieldnames) == {
            "units_version",
            "unit_system",
            "Date",
            "Type",
            "Amount",
            "Renewal Date",
            "Notes",
        }
        assert len(rows) == 1
        row = rows[0]
        assert row["units_version"] == "6"
        assert row["unit_system"] == "metric"
        assert row["Date"] == "2026-05-02"
        assert row["Type"] == "Registration"
        assert row["Amount"] == "120.50"
        assert row["Renewal Date"] == "2027-05-02"
        assert row["Notes"] == "Annual renewal"

    async def test_notes_csv_unchanged_except_version_cell(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        from app.models.note import Note

        vin = "SCHVERNOTES000001"
        await _make_vehicle(db_session, test_user, vin, "NotesSchemaVer")
        db_session.add(
            Note(
                vin=vin,
                date=date(2026, 5, 3),
                title="Reminder",
                content="Check tire pressure",
            )
        )
        await db_session.commit()

        response = await client.get(f"/api/export/vehicles/{vin}/notes/csv", headers=auth_headers)
        assert response.status_code == 200, response.text

        reader = csv.DictReader(io.StringIO(response.text))
        rows = list(reader)
        assert set(reader.fieldnames) == {
            "units_version",
            "unit_system",
            "Date",
            "Title",
            "Content",
        }
        assert len(rows) == 1
        row = rows[0]
        assert row["units_version"] == "6"
        assert row["unit_system"] == "metric"
        assert row["Date"] == "2026-05-03"
        assert row["Title"] == "Reminder"
        assert row["Content"] == "Check tire pressure"


class TestWarrantyInsuranceCSVPreExistingBug:
    """The other two dimensionless pairs cannot be pinned by a real row today.

    `export_warranties_csv` reads `record.coverage` / `record.cost` /
    `record.max_claims` / `record.terms`; `WarrantyRecord` has none of those
    attributes (it has `coverage_details`, and no cost/max_claims/terms
    column at all). `export_insurance_csv` reads `record.premium`;
    `InsurancePolicy` has `premium_amount`, not `premium`. Both are
    `AttributeError`s in the row-builder, so ANY seeded row 500s before a
    single CSV cell (including `units_version`) is ever written.

    Confirmed independently of this task's change (same crash reproduces
    identically before and after the constant split, since the split never
    touches these two functions' row-building code). Fixing the mismatch is
    a data-model question (drop the promised columns from the CSV, or add
    them to the model via a migration), not a mechanical rename, so it is
    out of scope for Task 1, whose only job is splitting the schema-version
    constant. Documented here rather than filed as a GitHub issue, per this
    project's convention of surfacing findings in the task report instead of
    stockpiling issues; flagged prominently in the Task 1 report for the
    phase's reviewer.

    These two `AttributeError` matches are the actual `str(exc)` this
    project's test container raised (captured while designing this test),
    not a guess at the failure mode.
    """

    async def test_warranty_csv_crashes_on_seeded_row_pre_existing_bug(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        from app.models.warranty import WarrantyRecord

        vin = "SCHVERWARR0000001"
        await _make_vehicle(db_session, test_user, vin, "WarrantySchemaVer")
        db_session.add(
            WarrantyRecord(
                vin=vin,
                warranty_type="Manufacturer",
                provider="Acme",
                start_date=date(2026, 1, 1),
            )
        )
        await db_session.commit()

        with pytest.raises(AttributeError, match="coverage"):
            await client.get(f"/api/export/vehicles/{vin}/warranties/csv", headers=auth_headers)

    async def test_insurance_csv_crashes_on_seeded_row_pre_existing_bug(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        from app.models.insurance import InsurancePolicy

        vin = "SCHVERINS00000001"
        await _make_vehicle(db_session, test_user, vin, "InsuranceSchemaVer")
        db_session.add(
            InsurancePolicy(
                vin=vin,
                provider="Acme",
                policy_number="P123",
                policy_type="Liability",
                start_date=date(2026, 1, 1),
                end_date=date(2027, 1, 1),
            )
        )
        await db_session.commit()

        with pytest.raises(AttributeError, match="premium"):
            await client.get(f"/api/export/vehicles/{vin}/insurance/csv", headers=auth_headers)


class TestCSVSchemaVersionAlsoAppliesToUnitBearingPairs:
    """`build_csv` (the four unit-bearing pairs) delegates to the same
    `generate_csv_stream`, so it must also emit "6". This is not one of the
    five dimensionless pairs from the phase brief, and no per-column pin is
    asserted here (that belongs to the later task that adds unit tokens to
    these headers) -- just confirmation the version split reaches this path
    too.
    """

    async def test_fuel_csv_emits_schema_version_6(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        from app.models.fuel import FuelRecord

        vin = "SCHVERFUEL0000001"
        await _make_vehicle(db_session, test_user, vin, "FuelSchemaVer")
        db_session.add(
            FuelRecord(
                vin=vin,
                date=date(2026, 5, 4),
                odometer_km=Decimal("1000.00"),
                liters=Decimal("40.0"),
                cost=Decimal("60.00"),
                is_full_tank=True,
            )
        )
        await db_session.commit()

        # `?units=metric` is explicit: from phase 2b task 3 an omitted
        # parameter exports in the CALLER's own units, and conftest's
        # `test_user` is an imperial-preset account. This test is about the
        # version cell, so it pins the unit system rather than inheriting it.
        response = await client.get(
            f"/api/export/vehicles/{vin}/fuel/csv?units=metric", headers=auth_headers
        )
        assert response.status_code == 200, response.text

        reader = csv.DictReader(io.StringIO(response.text))
        rows = list(reader)
        assert len(rows) == 1
        row = rows[0]
        assert row["units_version"] == "6"
        assert row["unit_system"] == "metric"


class TestJSONExportVersionUnchanged:
    """The JSON backup's `export_version` stays at the pre-split literal "5".

    Proves JSON_SCHEMA_VERSION did not silently move alongside CSV_SCHEMA_VERSION.
    """

    async def test_json_export_emits_schema_version_5(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        from app.models.hours import HoursRecord

        vin = "SCHVERJSON0000001"
        await _make_vehicle(db_session, test_user, vin, "JsonSchemaVer")
        db_session.add(
            HoursRecord(
                vin=vin,
                date=date(2026, 5, 5),
                engine_hours=Decimal("99.9"),
                notes="JSON pin",
                source="manual",
            )
        )
        await db_session.commit()

        response = await client.get(f"/api/export/vehicles/{vin}/json", headers=auth_headers)
        assert response.status_code == 200, response.text

        data = response.json()
        assert data["export_version"] == "5"
        assert data["units"] == "metric"
        matching = [r for r in data["hours_records"] if r["date"] == "2026-05-05"]
        assert len(matching) == 1
        assert matching[0]["engine_hours"] == 99.9
        assert matching[0]["notes"] == "JSON pin"

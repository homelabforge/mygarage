"""Warranty, insurance and tax CSV, in both directions.

Three record types were broken on both sides of the round trip:

* **Export** read attributes the model does not have. `WarrantyRecord.coverage`
  (it is `coverage_details`), plus `cost`, `deductible`, `max_claims` and
  `terms`, which do not exist at all; and `InsurancePolicy.premium` (it is
  `premium_amount`). Any vehicle with such a record returned 500.
* **Import** constructed with the same nonexistent kwargs, plus
  `TaxRecord(year=, paid_date=, due_date=, jurisdiction=)` -- four more. The
  `TypeError` was caught per row and reported as "Invalid record data", so the
  endpoint returned **200 while blaming the user's file** for an application
  bug. No tax record has ever imported successfully.
* The tax **export** was fine, which is why enumerating from the export bug
  never found the tax importer. Its headers (`Date`, `Renewal Date`) and its
  importer's headers (`Year`, `Paid Date`, `Due Date`, `Jurisdiction`) were
  different vocabularies, so the file it produced could not be read back even
  before the constructor raised.

The round trip is the assertion that covers all of it: export a record, import
the file, get the record back.
"""

import io
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.insurance import InsurancePolicy
from app.models.tax import TaxRecord
from app.models.warranty import WarrantyRecord


def _csv_rows(body: str) -> tuple[list[str], list[list[str]]]:
    import csv as _csv

    rows = list(_csv.reader(io.StringIO(body)))
    return rows[0], rows[1:]


@pytest.mark.asyncio
class TestWarrantyCsv:
    async def test_export_does_not_500_and_carries_the_real_fields(
        self, client: AsyncClient, db_session: AsyncSession, test_vehicle, auth_headers
    ):
        """The original defect: `record.coverage` raised AttributeError."""
        vin = str(test_vehicle["vin"])
        db_session.add(
            WarrantyRecord(
                vin=vin,
                warranty_type="Powertrain",
                provider="Acme",
                start_date=date(2026, 1, 1),
                end_date=date(2031, 1, 1),
                mileage_limit_km=Decimal("100000"),
                coverage_details="5yr / 100k",
                policy_number="W-123",
                notes="n",
            )
        )
        await db_session.commit()

        r = await client.get(f"/api/export/vehicles/{vin}/warranties/csv", headers=auth_headers)
        assert r.status_code == 200, r.text
        headers, rows = _csv_rows(r.text)
        assert "Coverage Details" in headers
        assert "Policy Number" in headers
        # The four with no model field are gone.
        for gone in ("Cost", "Max Claims", "Terms"):
            assert gone not in headers, f"{gone} has no source on WarrantyRecord"
        row = next(x for x in rows if x[headers.index("Provider")] == "Acme")
        assert row[headers.index("Coverage Details")] == "5yr / 100k"
        assert row[headers.index("Policy Number")] == "W-123"

    @pytest.mark.parametrize(
        "unit_query,header,expected",
        [("metric", "Mileage Limit (km)", "100000"), ("imperial", "Mileage Limit (mi)", "62137")],
    )
    async def test_mileage_limit_is_emitted_in_the_readers_units(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_vehicle,
        auth_headers,
        unit_query,
        header,
        expected,
    ):
        """`mileage_limit_km` is unit-bearing and was never exported at all.

        Asserts the TRANSFORMED value, not just the header: a test that checked
        only the dimensionless columns would pass with the conversion missing.
        """
        vin = str(test_vehicle["vin"])
        db_session.add(
            WarrantyRecord(
                vin=vin,
                warranty_type="Bumper-to-Bumper",
                provider="Units",
                start_date=date(2026, 2, 1),
                mileage_limit_km=Decimal("100000"),
            )
        )
        await db_session.commit()

        r = await client.get(
            f"/api/export/vehicles/{vin}/warranties/csv?units={unit_query}", headers=auth_headers
        )
        assert r.status_code == 200, r.text
        headers, rows = _csv_rows(r.text)
        assert header in headers, f"expected {header}, got {headers}"
        row = next(x for x in rows if x[headers.index("Provider")] == "Units")
        assert row[headers.index(header)].startswith(expected)

    async def test_round_trip(
        self, client: AsyncClient, db_session: AsyncSession, test_vehicle, auth_headers
    ):
        """Export, re-import, and get the record back.

        This is the assertion no earlier revision could write, because the
        importer was believed not to exist.
        """
        vin = str(test_vehicle["vin"])
        db_session.add(
            WarrantyRecord(
                vin=vin,
                warranty_type="Corrosion",
                provider="RoundTrip",
                start_date=date(2026, 3, 1),
                end_date=date(2030, 3, 1),
                mileage_limit_km=Decimal("80000"),
                coverage_details="perforation only",
                policy_number="RT-9",
                notes="keep me",
            )
        )
        await db_session.commit()

        exported = await client.get(
            f"/api/export/vehicles/{vin}/warranties/csv", headers=auth_headers
        )
        assert exported.status_code == 200

        await db_session.execute(WarrantyRecord.__table__.delete().where(WarrantyRecord.vin == vin))
        await db_session.commit()

        r = await client.post(
            f"/api/import/vehicles/{vin}/warranties/csv",
            files={"file": ("w.csv", exported.text, "text/csv")},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["error_count"] == 0, r.json()
        # Derived, not hardcoded: the suite shares one database and one VIN, so
        # earlier tests in this file have added warranties to the same vehicle
        # and the export carries them too. Every exported row must be ACCOUNTED
        # for -- imported or deduped -- and none may error. The parametrized
        # units test above writes two rows with the same (provider, start_date),
        # which is the importer's dedup key, so one of them is legitimately
        # skipped and asserting on success_count alone would be wrong.
        body = r.json()
        _, exported_rows = _csv_rows(exported.text)
        assert body["success_count"] + body["skipped_count"] == len(exported_rows), body
        assert body["success_count"] > 0, body

        back = (
            await db_session.execute(
                select(WarrantyRecord).where(WarrantyRecord.provider == "RoundTrip")
            )
        ).scalar_one()
        assert back.coverage_details == "perforation only"
        assert back.policy_number == "RT-9"
        assert back.mileage_limit_km == Decimal("80000")
        assert back.end_date == date(2030, 3, 1)


@pytest.mark.asyncio
class TestInsuranceCsv:
    async def test_export_does_not_500(
        self, client: AsyncClient, db_session: AsyncSession, test_vehicle, auth_headers
    ):
        vin = str(test_vehicle["vin"])
        db_session.add(
            InsurancePolicy(
                vin=vin,
                provider="Ins",
                policy_number="P-1",
                policy_type="Full Coverage",
                start_date=date(2026, 1, 1),
                end_date=date(2027, 1, 1),
                premium_amount=Decimal("123.45"),
                premium_frequency="Monthly",
                deductible=Decimal("500"),
            )
        )
        await db_session.commit()

        r = await client.get(f"/api/export/vehicles/{vin}/insurance/csv", headers=auth_headers)
        assert r.status_code == 200, r.text
        headers, rows = _csv_rows(r.text)
        assert "Premium" in headers and "Premium Frequency" in headers
        row = next(x for x in rows if x[headers.index("Policy Number")] == "P-1")
        assert row[headers.index("Premium")] == "123.45"
        assert row[headers.index("Premium Frequency")] == "Monthly"

    async def test_round_trip(
        self, client: AsyncClient, db_session: AsyncSession, test_vehicle, auth_headers
    ):
        vin = str(test_vehicle["vin"])
        db_session.add(
            InsurancePolicy(
                vin=vin,
                provider="InsRT",
                policy_number="P-RT",
                policy_type="Liability",
                start_date=date(2026, 4, 1),
                end_date=date(2027, 4, 1),
                premium_amount=Decimal("99.00"),
                premium_frequency="Annual",
                deductible=Decimal("250"),
                coverage_limits="100/300",
            )
        )
        await db_session.commit()

        exported = await client.get(
            f"/api/export/vehicles/{vin}/insurance/csv", headers=auth_headers
        )
        assert exported.status_code == 200
        await db_session.execute(
            InsurancePolicy.__table__.delete().where(InsurancePolicy.vin == vin)
        )
        await db_session.commit()

        r = await client.post(
            f"/api/import/vehicles/{vin}/insurance/csv",
            files={"file": ("i.csv", exported.text, "text/csv")},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["error_count"] == 0, r.json()

        back = (
            await db_session.execute(
                select(InsurancePolicy).where(InsurancePolicy.provider == "InsRT")
            )
        ).scalar_one()
        assert back.premium_amount == Decimal("99.00")
        assert back.premium_frequency == "Annual"
        assert back.deductible == Decimal("250")


@pytest.mark.asyncio
class TestTaxCsv:
    async def test_round_trip(
        self, client: AsyncClient, db_session: AsyncSession, test_vehicle, auth_headers
    ):
        """The one both earlier revisions missed.

        Tax export worked, so the bug was invisible from the export side. No
        tax record has ever imported: the constructor used four attributes the
        model does not have, and the importer read four headers the exporter
        does not write.
        """
        vin = str(test_vehicle["vin"])
        db_session.add(
            TaxRecord(
                vin=vin,
                date=date(2026, 5, 1),
                tax_type="Registration",
                amount=Decimal("212.00"),
                renewal_date=date(2027, 5, 1),
                notes="tax rt",
            )
        )
        await db_session.commit()

        exported = await client.get(f"/api/export/vehicles/{vin}/tax/csv", headers=auth_headers)
        assert exported.status_code == 200
        await db_session.execute(TaxRecord.__table__.delete().where(TaxRecord.vin == vin))
        await db_session.commit()

        r = await client.post(
            f"/api/import/vehicles/{vin}/tax/csv",
            files={"file": ("t.csv", exported.text, "text/csv")},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["error_count"] == 0, r.json()
        # Same accounting as the warranty round trip: the shared VIN carries
        # other tests' tax records, and the fixture data contains genuine
        # (date, tax_type) duplicates, which the importer's dedup key skips.
        # Every exported row must be accounted for; none may error.
        body = r.json()
        _, exported_rows = _csv_rows(exported.text)
        assert body["success_count"] + body["skipped_count"] == len(exported_rows), body
        assert body["success_count"] > 0, body

        back = (
            await db_session.execute(
                select(TaxRecord).where(TaxRecord.vin == vin, TaxRecord.notes == "tax rt")
            )
        ).scalar_one()
        assert back.date == date(2026, 5, 1)
        assert back.tax_type == "Registration"
        assert back.amount == Decimal("212.00")
        assert back.renewal_date == date(2027, 5, 1)


@pytest.mark.asyncio
class TestALegacyFileIsNotSilentlySwallowed:
    async def test_old_headers_report_the_real_problem(
        self, client: AsyncClient, test_vehicle, auth_headers
    ):
        """A pre-fix file must not come back 200 with every row blamed on the user.

        Asserted on `error_count`, not on the status code: 200 with
        `error_count == 1` and the message "Invalid record data" is exactly the
        current behaviour, and it must fail this test.
        """
        vin = str(test_vehicle["vin"])
        legacy = (
            "Provider,Type,Coverage,Start Date,End Date,Cost,Deductible,Max Claims,Terms,Notes\n"
            "Legacy,Powertrain,old coverage,2026-01-01,2031-01-01,10.00,50.00,3,terms,n\n"
        )
        r = await client.post(
            f"/api/import/vehicles/{vin}/warranties/csv",
            files={"file": ("legacy.csv", legacy, "text/csv")},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["error_count"] == 0, (
            f"a legacy file must be read, not blamed on the user: {body}"
        )
        assert body["success_count"] == 1

"""Integration tests for third-party fuel CSV import (Fuelio / Drivvo / Tesla)."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.models.fuel import FuelRecord
from app.models.odometer import OdometerRecord


@pytest.mark.integration
@pytest.mark.asyncio
class TestThirdPartyFuelImport:
    """Side effects, duplicate identity, and per-row failure isolation."""

    async def test_csv_import_syncs_odometer(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        """The importer had the same missing-side-effects defect as the webhook."""
        vin = test_vehicle["vin"]
        csv_data = "Date,Odometer,Liters,Price,Total cost\n2027-05-01,88123,40,1.50,60.00\n"
        files = {"file": ("fuelio.csv", csv_data, "text/csv")}
        response = await client.post(
            f"/api/import/vehicles/{vin}/fuel/fuelio",
            files=files,
            data={"skip_duplicates": "false"},
            headers=auth_headers,
        )
        assert response.json()["success_count"] == 1

        result = await db_session.execute(
            select(OdometerRecord).where(
                OdometerRecord.vin == vin,
                OdometerRecord.date == date(2027, 5, 1),
                OdometerRecord.source == "fuel",
            )
        )
        assert result.scalars().first() is not None, "CSV import did not sync odometer"

    async def test_same_date_syncs_only_the_highest_odometer(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        """Two fill-ups on one date must not let CSV order pick the stored value."""
        vin = test_vehicle["vin"]
        csv_data = (
            "Date,Odometer,Liters,Price,Total cost\n"
            "2027-05-09,90500,20,1.50,30.00\n"
            "2027-05-09,90100,20,1.50,30.00\n"
        )
        files = {"file": ("fuelio.csv", csv_data, "text/csv")}
        response = await client.post(
            f"/api/import/vehicles/{vin}/fuel/fuelio",
            files=files,
            data={"skip_duplicates": "false"},
            headers=auth_headers,
        )
        assert response.json()["success_count"] == 2

        result = await db_session.execute(
            select(OdometerRecord).where(
                OdometerRecord.vin == vin, OdometerRecord.date == date(2027, 5, 9)
            )
        )
        rows = result.scalars().all()
        assert len(rows) == 1
        assert Decimal(str(rows[0].odometer_km)) == Decimal("90500")

    async def test_one_bad_row_does_not_abort_the_file(self, test_vehicle, db_session, monkeypatch):
        """A row that fails to flush must not poison the rest of the batch."""
        from app.routes import import_data

        real_flush = db_session.flush
        calls = {"n": 0}

        async def flaky_flush(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("simulated flush failure")
            return await real_flush(*args, **kwargs)

        monkeypatch.setattr(db_session, "flush", flaky_flush)

        parsed = [
            {"date": date(2027, 6, 1), "odometer_km": Decimal("1000"), "liters": Decimal("40")},
            {"date": date(2027, 6, 2), "odometer_km": Decimal("1100"), "liters": Decimal("40")},
            {"date": date(2027, 6, 3), "odometer_km": Decimal("1200"), "liters": Decimal("40")},
        ]
        result = await import_data._persist_parsed_fuel(
            test_vehicle["vin"], parsed, False, db_session
        )
        assert result["success_count"] == 2
        assert result["error_count"] == 1

        rows = await db_session.execute(
            select(FuelRecord.date).where(FuelRecord.vin == test_vehicle["vin"])
        )
        dates = {d for (d,) in rows}
        assert date(2027, 6, 1) in dates
        assert date(2027, 6, 3) in dates
        assert date(2027, 6, 2) not in dates

    async def test_sync_failure_keeps_the_imported_rows(
        self, test_vehicle, db_session, monkeypatch
    ):
        """A failed derived odometer write must not cost the user their import."""
        from app.routes import import_data

        called: list[object] = []

        async def boom(*args, **kwargs):
            called.append(kwargs.get("date"))
            raise RuntimeError("simulated sync failure")

        monkeypatch.setattr(import_data, "sync_odometer_from_record", boom)

        parsed = [
            {"date": date(2027, 7, 1), "odometer_km": Decimal("1000"), "liters": Decimal("40")},
            {"date": date(2027, 7, 2), "odometer_km": Decimal("1100"), "liters": Decimal("40")},
        ]
        result = await import_data._persist_parsed_fuel(
            test_vehicle["vin"], parsed, False, db_session
        )
        assert result["success_count"] == 2
        # The patch reached the sync: a moved target would leave this test vacuous.
        assert called == [date(2027, 7, 1), date(2027, 7, 2)]

        count = await db_session.scalar(
            select(func.count())
            .select_from(FuelRecord)
            .where(
                FuelRecord.vin == test_vehicle["vin"],
                FuelRecord.date == date(2027, 7, 1),
            )
        )
        assert count == 1, "sync failure rolled back the fuel rows"

    async def test_same_date_different_energy_both_import(self, test_vehicle, db_session):
        """Two charge sessions can share a date and an odometer reading.

        Matching on (vin, date, odometer_km) alone silently dropped the second.
        """
        from app.routes.import_data import _persist_parsed_fuel

        parsed = [
            {
                "date": date(2027, 3, 1),
                "odometer_km": Decimal("50000"),
                "kwh": Decimal("45.5"),
                "price_basis": "per_kwh",
            },
            {
                "date": date(2027, 3, 1),
                "odometer_km": Decimal("50000"),
                "kwh": Decimal("12.0"),
                "price_basis": "per_kwh",
            },
        ]
        result = await _persist_parsed_fuel(test_vehicle["vin"], parsed, True, db_session)
        assert result["success_count"] == 2
        assert result["skipped_count"] == 0

    async def test_same_day_sessions_are_told_apart_by_time(self, test_vehicle, db_session):
        """Two charge sessions on one day differ by time, not by metadata.

        The adapters used to truncate the timestamp to a date, which left cost
        and location as the only distinguishing fields. Those are editable in the
        source app, so identity must not depend on them.
        """
        from app.routes.import_data import _persist_parsed_fuel

        base = {
            "date": date(2027, 3, 3),
            "odometer_km": Decimal("52000"),
            "kwh": Decimal("30.0"),
            "price_basis": "per_kwh",
        }
        parsed = [
            {**base, "filled_at": datetime(2027, 3, 3, 8, 15), "cost": Decimal("9.00")},
            {**base, "filled_at": datetime(2027, 3, 3, 19, 40), "cost": Decimal("18.00")},
        ]
        result = await _persist_parsed_fuel(test_vehicle["vin"], parsed, True, db_session)
        assert result["success_count"] == 2
        assert result["skipped_count"] == 0

    async def test_reimport_of_a_corrected_file_still_dedupes(self, test_vehicle, db_session):
        """Editing cost or notes in the source app must not create duplicates.

        This is why identity is the natural key of the event rather than every
        persisted column.
        """
        from app.routes.import_data import _persist_parsed_fuel

        base = {
            "date": date(2027, 3, 5),
            "filled_at": datetime(2027, 3, 5, 11, 0),
            "odometer_km": Decimal("53000"),
            "kwh": Decimal("30.0"),
            "price_basis": "per_kwh",
        }
        first = await _persist_parsed_fuel(
            test_vehicle["vin"], [{**base, "cost": Decimal("9.00")}], True, db_session
        )
        assert first["success_count"] == 1

        corrected = await _persist_parsed_fuel(
            test_vehicle["vin"],
            [{**base, "cost": Decimal("9.55"), "notes": "corrected in Tesla app"}],
            True,
            db_session,
        )
        assert corrected["success_count"] == 0
        assert corrected["skipped_count"] == 1

    @pytest.mark.parametrize(
        "field,value,reason",
        [
            ("charge_level", "Level 2", "charge_level must be one of L1, L2, DCFC"),
            ("charge_location", "work", "charge_location must be one of home, public"),
            (
                "price_basis",
                "per_gal",
                "price_basis must be one of per_volume, per_weight, per_tank, per_kwh",
            ),
        ],
    )
    async def test_a_word_outside_the_vocabulary_is_a_row_error(
        self, own_vehicle, db_session, field, value, reason
    ):
        """The parsers only map to known words, but a stored unknown one broke
        the fuel list, so the writer checks too. The reason never echoes the cell."""
        from app.routes.import_data import _persist_parsed_fuel

        row = {"date": date(2027, 8, 1), "odometer_km": Decimal("1000"), "kwh": Decimal("40")}
        result = await _persist_parsed_fuel(
            own_vehicle.vin, [{**row, field: value}], False, db_session
        )
        assert result["success_count"] == 0
        assert result["errors"] == [f"Row 2: {reason}"]
        assert value not in result["errors"][0]
        stored = await db_session.scalar(
            select(func.count()).select_from(FuelRecord).where(FuelRecord.vin == own_vehicle.vin)
        )
        assert stored == 0

    async def test_a_blank_word_still_imports(self, own_vehicle, db_session):
        """A guard: an empty cell isn't a word outside the vocabulary.

        Mutant: drop the `""` allowance from the import's vocabulary check.
        """
        from app.routes.import_data import _persist_parsed_fuel

        row = {"date": date(2027, 8, 2), "odometer_km": Decimal("1000"), "kwh": Decimal("40")}
        blank = dict.fromkeys(("charge_level", "charge_location", "price_basis"), "")
        result = await _persist_parsed_fuel(own_vehicle.vin, [{**row, **blank}], False, db_session)
        assert result["errors"] == []
        assert result["success_count"] == 1

    async def test_tesla_export_preserves_the_charge_time(self):
        """The time is the field that separates same-day sessions."""
        from app.services.import_adapters.fuel_csv import parse_tesla

        csv_data = (
            "Charge Start Date,Charge End Date,Energy Added (kWh),Cost\n"
            "2027-03-03 08:00:00,2027-03-03 08:45:00,30.0,9.00\n"
            "2027-03-03 19:10:00,2027-03-03 19:55:00,30.0,18.00\n"
        )
        rows = parse_tesla(csv_data)
        assert len(rows) == 2
        assert rows[0]["filled_at"] == datetime(2027, 3, 3, 8, 45)
        assert rows[1]["filled_at"] == datetime(2027, 3, 3, 19, 55)
        assert rows[0]["date"] == date(2027, 3, 3)

    async def test_date_only_export_has_no_timestamp(self):
        """A date-only export leaves filled_at NULL rather than inventing a time."""
        from app.services.import_adapters.fuel_csv import parse_fuelio

        rows = parse_fuelio("Date,Odometer,Liters\n2027-03-03,45000,40\n")
        assert rows[0]["filled_at"] is None

    async def test_truly_identical_rows_still_dedupe(self, test_engine, test_vehicle):
        """Regression guard, expected to pass before and after this task.

        Uses an explicitly non-autoflushing session, pinning production's
        setting (app/database.py:84) directly over test_engine, independent
        of conftest's test_sessionmaker.
        """
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from app.routes.import_data import _persist_parsed_fuel

        maker = async_sessionmaker(
            test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
        )
        row = {
            "date": date(2027, 3, 2),
            "odometer_km": Decimal("51000"),
            "kwh": Decimal("45.5"),
            "price_basis": "per_kwh",
        }
        async with maker() as session:
            result = await _persist_parsed_fuel(
                test_vehicle["vin"], [dict(row), dict(row)], True, session
            )
        assert result["success_count"] == 1
        assert result["skipped_count"] == 1

    async def test_miles_form_field_converts_odometer(
        self, client: AsyncClient, auth_headers, test_vehicle, db_session
    ):
        vin = test_vehicle["vin"]
        csv_data = "Date,Odometer,Gallons,Price,Total cost\n2027-04-01,10000,10,3.50,35.00\n"
        files = {"file": ("fuelio.csv", csv_data, "text/csv")}
        response = await client.post(
            f"/api/import/vehicles/{vin}/fuel/fuelio",
            files=files,
            data={"skip_duplicates": "false", "odometer_unit": "mi"},
            headers=auth_headers,
        )
        assert response.json()["success_count"] == 1

        result = await db_session.execute(
            select(FuelRecord.odometer_km)
            .where(FuelRecord.vin == vin, FuelRecord.date == date(2027, 4, 1))
            .order_by(FuelRecord.id.desc())
        )
        # 10000 mi -> 16093.44 km
        assert Decimal(str(result.scalars().first())) == Decimal("16093.44")

    async def test_bad_unit_is_rejected(self, client: AsyncClient, auth_headers, test_vehicle):
        files = {"file": ("f.csv", "Date,Odometer,Liters\n2027-04-01,1,1\n", "text/csv")}
        response = await client.post(
            f"/api/import/vehicles/{test_vehicle['vin']}/fuel/fuelio",
            files=files,
            data={"odometer_unit": "furlongs"},
            headers=auth_headers,
        )
        assert response.status_code == 400

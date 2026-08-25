"""The UK gallon setting must never change how a stored file is read.

Originally, `UnitConverter.GALLONS_TO_LITERS` was a mutable class attribute
repointed process-wide by the `imperial_gallon_standard` setting. The
legacy-format converters in `import_data.py` and the imperial export in
`export.py` both read it, so on a UK-configured instance:

- importing a v2-era backup (always US gallons) multiplied every volume by
  4.54609 instead of 3.78541 and wrote that into canonical storage, permanently;
- the imperial export emitted UK gallons under a "Gallons" header that the
  importer then read back as US.

The fix makes the file itself authoritative: an export declares its flavour in
the `unit_system` marker, and anything not marked `imperial_uk` is US.

Units phase 0 (Task 2/3) then deleted that mutable class state entirely.
`export.py` now resolves the flavour explicitly per request via
`resolve_gallon_flavour(db)`, which reads the `imperial_gallon_standard`
`Setting` row. The `uk_gallons` fixture below seeds that row directly instead
of reaching into `UnitConverter` internals, so these tests exercise the real
resolution path end to end.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.models.fuel import FuelRecord
from app.models.settings import Setting
from app.models.vehicle import Vehicle

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

US_GAL_L = Decimal("3.78541")
UK_GAL_L = Decimal("4.54609")

GALLON_STANDARD_KEY = "imperial_gallon_standard"


async def _set_gallon_standard(db_session, value: str) -> None:
    """Upsert the `imperial_gallon_standard` setting row."""
    existing = (
        await db_session.execute(select(Setting).where(Setting.key == GALLON_STANDARD_KEY))
    ).scalar_one_or_none()
    if existing is None:
        db_session.add(Setting(key=GALLON_STANDARD_KEY, value=value))
    else:
        existing.value = value
    await db_session.commit()


@pytest_asyncio.fixture
async def uk_gallons(db_session):
    """Seed the instance's `imperial_gallon_standard` setting to UK, then restore
    whatever was genuinely there beforehand -- including row absence.

    Exercises the same `resolve_gallon_flavour(db)` path the route uses at
    request time, rather than reaching past it into `UnitConverter` class
    internals (deleted in Task 2 — there is no class state left to set).

    This used to hardcode the restore to "us", which left a row behind even
    when none existed before this fixture ran. That made
    `test_defaults_to_us_when_row_absent` in test_gallon_flavour.py pass only
    by accident of which test file happened to run first (see
    reference_mygarage_test_isolation): correct by luck, not by design.
    Restoring the actual prior state removes that landmine.
    """
    existing = (
        await db_session.execute(select(Setting).where(Setting.key == GALLON_STANDARD_KEY))
    ).scalar_one_or_none()
    original_value = existing.value if existing is not None else None

    await _set_gallon_standard(db_session, "uk")
    try:
        yield
    finally:
        if original_value is None:
            row = (
                await db_session.execute(select(Setting).where(Setting.key == GALLON_STANDARD_KEY))
            ).scalar_one_or_none()
            if row is not None:
                await db_session.delete(row)
                await db_session.commit()
        else:
            await _set_gallon_standard(db_session, original_value)


async def _make_vehicle(db_session, test_user, vin: str) -> None:
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=test_user["id"],
            nickname=vin,
            vehicle_type="Car",
            year=2024,
            make="Test",
            model="Gallons",
        )
    )
    await db_session.commit()


class TestGallonStandardRoundTrip:
    async def test_uk_export_declares_its_flavour_and_round_trips(
        self, client: AsyncClient, auth_headers, test_user, db_session, uk_gallons
    ):
        """A UK imperial export must import back to the same canonical liters."""
        src, dst = "UKGALSRC000000001", "UKGALDST000000001"
        await _make_vehicle(db_session, test_user, src)
        await _make_vehicle(db_session, test_user, dst)
        db_session.add(
            FuelRecord(
                vin=src,
                date=date(2026, 5, 18),
                odometer_km=Decimal("500.00"),
                liters=Decimal("45.461"),
                price_per_unit=Decimal("1.500"),
                price_basis="per_volume",
                cost=Decimal("68.19"),
                is_full_tank=True,
            )
        )
        await db_session.commit()

        export_resp = await client.get(
            f"/api/export/vehicles/{src}/fuel/csv?units=imperial", headers=auth_headers
        )
        assert export_resp.status_code == 200

        body = export_resp.content.decode()
        rows = list(csv.DictReader(io.StringIO(body)))
        # The file says which gallon it is in. Without this the importer cannot
        # tell a UK export from a US one and has to guess.
        assert rows[0]["unit_system"] == "imperial_uk"
        # 45.461 L / 4.54609 = 10.0 UK gal (not 12.01 US gal)
        assert float(rows[0]["Gallons"]) == pytest.approx(10.0, abs=0.01)

        import_resp = await client.post(
            f"/api/import/vehicles/{dst}/fuel/csv",
            headers=auth_headers,
            files={"file": ("fuel.csv", io.BytesIO(export_resp.content), "text/csv")},
        )
        assert import_resp.status_code == 200, import_resp.text
        assert import_resp.json()["success_count"] == 1

        row = (
            await db_session.execute(select(FuelRecord).where(FuelRecord.vin == dst))
        ).scalar_one()
        assert float(row.liters) == pytest.approx(45.461, abs=0.01)

    async def test_unmarked_legacy_csv_is_us_gallons_even_on_a_uk_instance(
        self, client: AsyncClient, auth_headers, test_user, db_session, uk_gallons
    ):
        """The corruption case: a v2-era file has no marker and is always US."""
        vin = "UKGALLEGACY000001"
        await _make_vehicle(db_session, test_user, vin)

        # Exactly the shape MyGarage v2 wrote: imperial column names, no markers.
        legacy_csv = (
            "Date,Mileage,Gallons,Price Per Gallon,Total Cost,Full Tank\n"
            "2024-03-01,10000,10.0,3.00,30.00,True\n"
        )
        resp = await client.post(
            f"/api/import/vehicles/{vin}/fuel/csv",
            headers=auth_headers,
            files={"file": ("legacy.csv", io.BytesIO(legacy_csv.encode()), "text/csv")},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["success_count"] == 1

        row = (
            await db_session.execute(select(FuelRecord).where(FuelRecord.vin == vin))
        ).scalar_one()
        # 10 US gal = 37.8541 L. Reading it as UK would store 45.4609 L, a
        # permanent 20 percent inflation of the user's history.
        assert float(row.liters) == pytest.approx(float(Decimal("10") * US_GAL_L), abs=0.01)
        assert float(row.liters) != pytest.approx(float(Decimal("10") * UK_GAL_L), abs=0.01)

    async def test_us_export_still_says_imperial_and_uses_us_gallons(
        self, client: AsyncClient, auth_headers, test_user, db_session
    ):
        """The default path must be untouched: marker `imperial`, US divisor."""
        vin = "USGALSRC000000001"
        await _make_vehicle(db_session, test_user, vin)
        db_session.add(
            FuelRecord(
                vin=vin,
                date=date(2026, 5, 18),
                odometer_km=Decimal("500.00"),
                liters=Decimal("37.8541"),
                is_full_tank=True,
            )
        )
        await db_session.commit()

        resp = await client.get(
            f"/api/export/vehicles/{vin}/fuel/csv?units=imperial", headers=auth_headers
        )
        assert resp.status_code == 200
        rows = list(csv.DictReader(io.StringIO(resp.content.decode())))
        assert rows[0]["unit_system"] == "imperial"
        assert float(rows[0]["Gallons"]) == pytest.approx(10.0, abs=0.01)

    async def test_metric_export_is_unaffected_by_the_uk_setting(
        self, client: AsyncClient, auth_headers, test_user, db_session, uk_gallons
    ):
        """Canonical storage is metric; the setting is an imperial-display choice."""
        vin = "UKGALMETRIC000001"
        await _make_vehicle(db_session, test_user, vin)
        db_session.add(
            FuelRecord(
                vin=vin,
                date=date(2026, 5, 18),
                odometer_km=Decimal("500.00"),
                liters=Decimal("40.000"),
                is_full_tank=True,
            )
        )
        await db_session.commit()

        resp = await client.get(f"/api/export/vehicles/{vin}/fuel/csv", headers=auth_headers)
        assert resp.status_code == 200
        rows = list(csv.DictReader(io.StringIO(resp.content.decode())))
        assert rows[0]["unit_system"] == "metric"
        assert float(rows[0]["Liters"]) == pytest.approx(40.0, abs=0.001)

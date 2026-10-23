"""Skip duplicates still recognises a row stored with the old conversion factors.

Before v3.4.0 a mile was converted with 1.60934 km and a US gallon with
3.78541 L; both are now the exact definitions (1.609344 km, 3.785411784 L).
45,000 mi typed before the upgrade is stored as 72420.30 km, and the same
45,000 mi converts to 72420.48 km today. A duplicate check that compares the
odometer for equality treats those as two different fill-ups, so re-importing
an old backup, or a new export of the old row, imports every imperial record a
second time.

Every expected figure below is computed here from both factors with
`Decimal`, never read back from the code under test. The old factors appear
only as history: they are what pre-upgrade rows were written with.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.def_record import DEFRecord
from app.models.fuel import FuelRecord
from app.models.odometer import OdometerRecord
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.models.vehicle import Vehicle

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

#: The mile pre-upgrade rows were converted with (history, not a factor in use).
OLD_MILE_KM = Decimal("1.60934")
#: The international mile, exact by definition.
MILE_KM = Decimal("1.609344")
#: The US gallon pre-upgrade rows were converted with (history).
OLD_US_GALLON_L = Decimal("3.78541")
#: The US gallon, exact by definition.
US_GALLON_L = Decimal("3.785411784")

#: Odometer columns are NUMERIC(10, 2); volume columns NUMERIC(9, 3).
KM_STEP = Decimal("0.01")
LITRE_STEP = Decimal("0.001")
#: Export writes distance in miles to three decimals.
EXPORT_MILE_STEP = Decimal("0.001")

DAY = date(2026, 3, 1)


def stored_before_upgrade(miles: str) -> Decimal:
    """The odometer column's value for `miles` typed before the upgrade."""
    return (Decimal(miles) * OLD_MILE_KM).quantize(KM_STEP)


def converted_today(miles: str) -> Decimal:
    """The canonical km the importer computes for `miles` today."""
    return Decimal(miles) * MILE_KM


@pytest.fixture(autouse=True)
def _reset_import_rate_limit():
    """Clear the shared import and export limiter storage between tests.

    Every import endpoint shares one module-level limiter, and the export
    round trip below also spends the export limiter. Mirrors
    `test_import_data.py`.
    """
    from app.routes.export import limiter as export_limiter
    from app.routes.import_data import limiter as import_limiter

    for lim in (import_limiter, export_limiter):
        storage = lim._storage
        storage.storage.clear()
        storage.expirations.clear()
        if hasattr(storage, "events"):
            storage.events.clear()


@asynccontextmanager
async def _vehicle(db_session: AsyncSession, user_id: object, vin: str) -> AsyncIterator[str]:
    """A committed diesel vehicle, with every row this file writes removed after."""
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=user_id,
            nickname=vin,
            vehicle_type="Car",
            # Diesel so the DEF importer's fuel-type gate accepts the vehicle.
            fuel_type="diesel",
        )
    )
    await db_session.commit()
    try:
        yield vin
    finally:
        await db_session.rollback()
        visit_ids = (
            (await db_session.execute(select(ServiceVisit.id).where(ServiceVisit.vin == vin)))
            .scalars()
            .all()
        )
        if visit_ids:
            await db_session.execute(
                delete(ServiceLineItem).where(ServiceLineItem.visit_id.in_(visit_ids))
            )
        for model in (OdometerRecord, ServiceVisit, FuelRecord, DEFRecord):
            await db_session.execute(delete(model).where(model.vin == vin))
        await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
        await db_session.commit()


async def _count(db_session: AsyncSession, model, vin: str) -> int:
    """How many `model` rows `vin` holds on DAY."""
    result = await db_session.execute(
        select(func.count()).select_from(model).where(model.vin == vin, model.date == DAY)
    )
    return int(result.scalar_one())


async def _post_csv(client: AsyncClient, headers, vin: str, pair: str, body: str):
    """Upload one CSV with skip duplicates on."""
    return await client.post(
        f"/api/import/vehicles/{vin}/{pair}/csv",
        headers=headers,
        files={"file": (f"{pair}.csv", BytesIO(body.encode()), "text/csv")},
        data={"skip_duplicates": "true"},
    )


class TestTheScenarioIsReal:
    async def test_the_two_factors_store_different_figures(self):
        """Precondition for every test below: without it they prove nothing."""
        assert stored_before_upgrade("45000") == Decimal("72420.30")
        assert converted_today("45000") == Decimal("72420.48")
        re_exported = (stored_before_upgrade("45000") / MILE_KM).quantize(EXPORT_MILE_STEP)
        assert re_exported == Decimal("44999.888")
        assert converted_today("44999.888") == Decimal("72420.299753472")
        assert converted_today("44999.888") != stored_before_upgrade("45000")


class TestCsvImportersSkipAPreUpgradeRow:
    async def test_service(self, client, auth_headers, test_user, db_session):
        async with _vehicle(db_session, test_user["id"], "DRIFTSVC000000001") as vin:
            db_session.add(
                ServiceVisit(
                    vin=vin,
                    date=DAY,
                    odometer_km=stored_before_upgrade("45000"),
                    service_category="Maintenance",
                    total_cost=Decimal("10"),
                )
            )
            await db_session.commit()
            body = (
                "units_version,unit_system,Date,Category,Odometer (mi),Cost\n"
                "6,imperial,2026-03-01,Maintenance,45000,10\n"
            )
            resp = await _post_csv(client, auth_headers, vin, "service", body)
            assert resp.status_code == 200, resp.text
            assert resp.json()["skipped_count"] == 1, resp.json()
            assert await _count(db_session, ServiceVisit, vin) == 1

    @pytest.mark.parametrize("miles", ["45000", "44999.888"])
    async def test_fuel(self, client, auth_headers, test_user, db_session, miles):
        """45000 is the figure the user typed; 44999.888 is today's export of the stored row."""
        async with _vehicle(db_session, test_user["id"], "DRIFTFUEL00000001") as vin:
            db_session.add(
                FuelRecord(
                    vin=vin,
                    date=DAY,
                    odometer_km=stored_before_upgrade("45000"),
                    liters=Decimal("47.318"),
                    is_full_tank=True,
                )
            )
            await db_session.commit()
            body = (
                "units_version,unit_system,Date,Odometer (mi),Volume (gal_us)\n"
                f"6,imperial,2026-03-01,{miles},12.5\n"
            )
            resp = await _post_csv(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 200, resp.text
            assert resp.json()["skipped_count"] == 1, resp.json()
            assert await _count(db_session, FuelRecord, vin) == 1

    async def test_def(self, client, auth_headers, test_user, db_session):
        async with _vehicle(db_session, test_user["id"], "DRIFTDEF000000001") as vin:
            db_session.add(
                DEFRecord(
                    vin=vin,
                    date=DAY,
                    odometer_km=stored_before_upgrade("45000"),
                    liters=Decimal("9.464"),
                )
            )
            await db_session.commit()
            body = "units_version,unit_system,Date,Odometer (mi)\n6,imperial,2026-03-01,45000\n"
            resp = await _post_csv(client, auth_headers, vin, "def", body)
            assert resp.status_code == 200, resp.text
            assert resp.json()["skipped_count"] == 1, resp.json()
            assert await _count(db_session, DEFRecord, vin) == 1

    async def test_odometer(self, client, auth_headers, test_user, db_session):
        async with _vehicle(db_session, test_user["id"], "DRIFTODO000000001") as vin:
            db_session.add(
                OdometerRecord(vin=vin, date=DAY, odometer_km=stored_before_upgrade("45000"))
            )
            await db_session.commit()
            body = "units_version,unit_system,Date,Reading (mi)\n6,imperial,2026-03-01,45000\n"
            resp = await _post_csv(client, auth_headers, vin, "odometer", body)
            assert resp.status_code == 200, resp.text
            assert resp.json()["skipped_count"] == 1, resp.json()
            assert await _count(db_session, OdometerRecord, vin) == 1

    async def test_fuel_export_then_re_import(self, client, auth_headers, test_user, db_session):
        """The user-facing round trip: export the pre-upgrade row today, import it back."""
        async with _vehicle(db_session, test_user["id"], "DRIFTROUND0000001") as vin:
            db_session.add(
                FuelRecord(
                    vin=vin,
                    date=DAY,
                    odometer_km=stored_before_upgrade("45000"),
                    liters=Decimal("47.318"),
                    is_full_tank=True,
                )
            )
            await db_session.commit()
            exported = await client.get(
                f"/api/export/vehicles/{vin}/fuel/csv?units=imperial", headers=auth_headers
            )
            assert exported.status_code == 200, exported.text
            row = next(csv.DictReader(io.StringIO(exported.text)))
            expected_cell = (stored_before_upgrade("45000") / MILE_KM).quantize(EXPORT_MILE_STEP)
            assert Decimal(row["Odometer (mi)"]) == expected_cell

            resp = await _post_csv(client, auth_headers, vin, "fuel", exported.text)
            assert resp.status_code == 200, resp.text
            assert resp.json()["skipped_count"] == 1, resp.json()
            assert await _count(db_session, FuelRecord, vin) == 1

    async def test_a_row_already_stored_twice_is_skipped_not_an_error(
        self, client, auth_headers, test_user, db_session
    ):
        """A band can match more than one stored row; any match means skip.

        Asking for exactly one match turned a vehicle that already held the
        fill-up twice into a reported row error on every later re-import.
        """
        async with _vehicle(db_session, test_user["id"], "DRIFTTWICE0000001") as vin:
            for _ in range(2):
                db_session.add(
                    FuelRecord(
                        vin=vin,
                        date=DAY,
                        odometer_km=stored_before_upgrade("45000"),
                        liters=Decimal("47.318"),
                    )
                )
            await db_session.commit()
            body = "units_version,unit_system,Date,Odometer (mi)\n6,imperial,2026-03-01,45000\n"
            resp = await _post_csv(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 200, resp.text
            assert resp.json()["error_count"] == 0, resp.json()
            assert resp.json()["skipped_count"] == 1, resp.json()
            assert await _count(db_session, FuelRecord, vin) == 2

    async def test_a_low_odometer_rounded_down_on_storage(
        self, client, auth_headers, test_user, db_session
    ):
        """Both allowances at once: the factor drift and the column's rounding.

        2008 mi was 3231.55472 km with the old mile, stored rounded down to
        3231.55. Today it converts to 3231.562752 km: 0.012752 km away, more
        than either allowance alone covers at this odometer.
        """
        stored = stored_before_upgrade("2008")
        assert stored == Decimal("3231.55")
        today = converted_today("2008")
        assert today == Decimal("3231.562752")
        assert today - stored > max(KM_STEP, today * Decimal("3e-6"))
        async with _vehicle(db_session, test_user["id"], "DRIFTLOW000000001") as vin:
            db_session.add(FuelRecord(vin=vin, date=DAY, odometer_km=stored, liters=Decimal("30")))
            await db_session.commit()
            body = "units_version,unit_system,Date,Odometer (mi)\n6,imperial,2026-03-01,2008\n"
            resp = await _post_csv(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 200, resp.text
            assert resp.json()["skipped_count"] == 1, resp.json()
            assert await _count(db_session, FuelRecord, vin) == 1


class TestADifferentOdometerOnTheSameDayStillImports:
    @pytest.mark.parametrize("miles", ["45010", "45000.5"])
    async def test_fuel(self, client, auth_headers, test_user, db_session, miles):
        """45,010 mi is 16 km on; 45,000.5 mi is under a kilometre on, still a new fill-up."""
        stored = stored_before_upgrade("45000")
        assert converted_today(miles) - stored > Decimal("0.5")
        async with _vehicle(db_session, test_user["id"], "DRIFTGUARD0000001") as vin:
            db_session.add(
                FuelRecord(vin=vin, date=DAY, odometer_km=stored, liters=Decimal("47.318"))
            )
            await db_session.commit()
            body = (
                "units_version,unit_system,Date,Odometer (mi),Volume (gal_us)\n"
                f"6,imperial,2026-03-01,{miles},12.5\n"
            )
            resp = await _post_csv(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 200, resp.text
            assert resp.json()["success_count"] == 1, resp.json()
            assert resp.json()["skipped_count"] == 0, resp.json()
            assert await _count(db_session, FuelRecord, vin) == 2


class TestLegacyJsonBackupSkipsPreUpgradeRows:
    async def test_every_odometer_keyed_section(self, client, auth_headers, test_user, db_session):
        """A v2 backup carries miles, converted on ingest in every section."""
        stored = stored_before_upgrade("45000")
        async with _vehicle(db_session, test_user["id"], "DRIFTJSON00000001") as vin:
            db_session.add_all(
                [
                    ServiceVisit(
                        vin=vin,
                        date=DAY,
                        odometer_km=stored,
                        service_category="Maintenance",
                        total_cost=Decimal("10"),
                    ),
                    FuelRecord(vin=vin, date=DAY, odometer_km=stored, liters=Decimal("47.318")),
                    DEFRecord(vin=vin, date=DAY, odometer_km=stored, liters=Decimal("9.464")),
                    OdometerRecord(vin=vin, date=DAY, odometer_km=stored),
                ]
            )
            await db_session.commit()
            backup = {
                "service_records": [
                    {"date": "2026-03-01", "mileage": 45000, "service_type": "Oil", "cost": 10}
                ],
                "fuel_records": [{"date": "2026-03-01", "mileage": 45000, "gallons": 12.5}],
                "def_records": [{"date": "2026-03-01", "mileage": 45000, "gallons": 2.5}],
                "odometer_records": [{"date": "2026-03-01", "reading": 45000}],
            }
            resp = await client.post(
                f"/api/import/vehicles/{vin}/json",
                headers=auth_headers,
                files={
                    "file": ("v2.json", BytesIO(json.dumps(backup).encode()), "application/json")
                },
                data={"skip_duplicates": "true"},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            for section in ("service_records", "fuel_records", "def_records", "odometer_records"):
                assert data[section]["skipped_count"] == 1, (section, data)
            assert await _count(db_session, ServiceVisit, vin) == 1
            assert await _count(db_session, FuelRecord, vin) == 1
            assert await _count(db_session, DEFRecord, vin) == 1
            assert await _count(db_session, OdometerRecord, vin) == 1


class TestThirdPartyImportSkipsAPreUpgradeRow:
    async def test_fuelio_in_miles_and_gallons(self, client, auth_headers, test_user, db_session):
        """Its duplicate key also compares the volume, converted from gallons the same way."""
        stored_litres = (Decimal("12.5") * OLD_US_GALLON_L).quantize(LITRE_STEP)
        assert stored_litres == Decimal("47.318")
        assert Decimal("12.5") * US_GALLON_L == Decimal("47.3176473000")
        async with _vehicle(db_session, test_user["id"], "DRIFTFUELIO000001") as vin:
            db_session.add(
                FuelRecord(
                    vin=vin,
                    date=DAY,
                    odometer_km=stored_before_upgrade("45000"),
                    liters=stored_litres,
                    is_full_tank=True,
                )
            )
            await db_session.commit()
            resp = await client.post(
                f"/api/import/vehicles/{vin}/fuel/fuelio",
                headers=auth_headers,
                files={
                    "file": (
                        "fuelio.csv",
                        "Date,Odometer,Gallons,Price,Total cost\n2026-03-01,45000,12.5,3.50,43.75\n",
                        "text/csv",
                    )
                },
                data={"skip_duplicates": "true", "odometer_unit": "mi"},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["skipped_count"] == 1, resp.json()
            assert await _count(db_session, FuelRecord, vin) == 1


#: Two genuinely different readings on the same day, 200 m apart. The drift
#: band at this odometer is 0.30 km plus the 0.01 km step, so both sit inside
#: it: exactly the pair an unconditional band skips as a duplicate.
FIRST_KM = Decimal("100000.00")
SECOND_KM = Decimal("100000.20")
#: The imperial pair: 0.1 mi (161 m) apart, also inside the band once converted.
FIRST_MI = "62137.0"
SECOND_MI = "62137.1"

#: pair -> (model, CSV header after the marker columns, data row template).
_CSV_PAIRS = {
    "odometer": (OdometerRecord, "Date,Reading ({u})", "2026-03-01,{v}"),
    "fuel": (FuelRecord, "Date,Odometer ({u}),Volume (L)", "2026-03-01,{v},40"),
    "def": (DEFRecord, "Date,Odometer ({u})", "2026-03-01,{v}"),
    "service": (ServiceVisit, "Date,Category,Odometer ({u}),Cost", "2026-03-01,Maintenance,{v},10"),
}


def _csv(pair: str, system: str, unit: str, values: list[str]) -> str:
    """A v6 CSV for `pair` carrying one row per odometer in `values`."""
    _, header, row = _CSV_PAIRS[pair]
    lines = [f"units_version,unit_system,{header.format(u=unit)}"]
    lines += [f"6,{system},{row.format(v=v)}" for v in values]
    return "\n".join(lines) + "\n"


def _stored(pair: str, vin: str, odometer_km: Decimal):
    """A row `pair`'s importer compares against, stored before the import."""
    return {
        "odometer": lambda: OdometerRecord(vin=vin, date=DAY, odometer_km=odometer_km),
        "fuel": lambda: FuelRecord(
            vin=vin, date=DAY, odometer_km=odometer_km, liters=Decimal("40"), is_full_tank=True
        ),
        "def": lambda: DEFRecord(vin=vin, date=DAY, odometer_km=odometer_km, liters=Decimal("9")),
        "service": lambda: ServiceVisit(
            vin=vin,
            date=DAY,
            odometer_km=odometer_km,
            service_category="Maintenance",
            total_cost=Decimal("10"),
        ),
    }[pair]()


class TestTwoDifferentReadingsInsideTheBandBothImport:
    """The band's other side: it must never swallow a second, different reading.

    Applied to every duplicate check, the band skipped the second of two genuine
    same-day readings: the check queries the table, where a row this import has
    already written is visible, and a stored reading was matched the same way.
    Only a value converted from miles or gallons in this import, meeting a row
    stored before the import began, can be the drift the band exists for.
    """

    def test_the_pairs_are_inside_the_band(self):
        """Precondition: without it every test below passes for the wrong reason."""
        band = SECOND_KM * Decimal("3e-6") + KM_STEP
        assert Decimal("0.01") < SECOND_KM - FIRST_KM < band
        imperial_gap = converted_today(SECOND_MI) - converted_today(FIRST_MI)
        assert KM_STEP < imperial_gap < converted_today(SECOND_MI) * Decimal("3e-6") + KM_STEP

    @pytest.mark.parametrize("pair", list(_CSV_PAIRS))
    async def test_metric_csv_two_readings_in_one_file(
        self, client, auth_headers, test_user, db_session, pair
    ):
        model = _CSV_PAIRS[pair][0]
        async with _vehicle(db_session, test_user["id"], f"BANDMCSV{pair.upper():0<9}") as vin:
            body = _csv(pair, "metric", "km", [str(FIRST_KM), str(SECOND_KM)])
            resp = await _post_csv(client, auth_headers, vin, pair, body)
            assert resp.status_code == 200, resp.text
            assert resp.json()["success_count"] == 2, resp.json()
            assert resp.json()["skipped_count"] == 0, resp.json()
            assert await _count(db_session, model, vin) == 2

    @pytest.mark.parametrize("pair", list(_CSV_PAIRS))
    async def test_metric_csv_reading_next_to_a_stored_one(
        self, client, auth_headers, test_user, db_session, pair
    ):
        """A reading already stored (LiveLink, a manual entry) plus a different one from a file."""
        model = _CSV_PAIRS[pair][0]
        async with _vehicle(db_session, test_user["id"], f"BANDNEXT{pair.upper():0<9}") as vin:
            db_session.add(_stored(pair, vin, FIRST_KM))
            await db_session.commit()
            body = _csv(pair, "metric", "km", [str(SECOND_KM)])
            resp = await _post_csv(client, auth_headers, vin, pair, body)
            assert resp.status_code == 200, resp.text
            assert resp.json()["success_count"] == 1, resp.json()
            assert await _count(db_session, model, vin) == 2

    @pytest.mark.parametrize("pair", list(_CSV_PAIRS))
    async def test_metric_csv_same_reading_is_still_skipped(
        self, client, auth_headers, test_user, db_session, pair
    ):
        """Narrowing the band must not stop the ordinary re-import being skipped."""
        model = _CSV_PAIRS[pair][0]
        async with _vehicle(db_session, test_user["id"], f"BANDSAME{pair.upper():0<9}") as vin:
            db_session.add(_stored(pair, vin, SECOND_KM))
            await db_session.commit()
            body = _csv(pair, "metric", "km", [str(SECOND_KM)])
            resp = await _post_csv(client, auth_headers, vin, pair, body)
            assert resp.status_code == 200, resp.text
            assert resp.json()["skipped_count"] == 1, resp.json()
            assert await _count(db_session, model, vin) == 1

    @pytest.mark.parametrize("pair", list(_CSV_PAIRS))
    async def test_metric_csv_readings_one_column_step_apart_are_different(
        self, client, auth_headers, test_user, db_session, pair
    ):
        """10 m is still a different reading at the column's precision.

        PostgreSQL casts a bound parameter to the column's NUMERIC(10, 2), which
        rounds a window edge of 100000.005 up to 100000.01. A window typed like
        the column therefore swallowed the next step on PostgreSQL only.
        """
        model = _CSV_PAIRS[pair][0]
        async with _vehicle(db_session, test_user["id"], f"BANDSTEP{pair.upper():0<9}") as vin:
            db_session.add(_stored(pair, vin, Decimal("100000.01")))
            await db_session.commit()
            body = _csv(pair, "metric", "km", ["100000.00"])
            resp = await _post_csv(client, auth_headers, vin, pair, body)
            assert resp.status_code == 200, resp.text
            assert resp.json()["success_count"] == 1, resp.json()
            assert await _count(db_session, model, vin) == 2

    @pytest.mark.parametrize("pair", list(_CSV_PAIRS))
    async def test_metric_csv_finer_than_the_column_matches_its_stored_rounding(
        self, client, auth_headers, test_user, db_session, pair
    ):
        """100000.204 km would be stored as 100000.20, so it is that row, not a new one."""
        model = _CSV_PAIRS[pair][0]
        async with _vehicle(db_session, test_user["id"], f"BANDFINE{pair.upper():0<9}") as vin:
            db_session.add(_stored(pair, vin, SECOND_KM))
            await db_session.commit()
            body = _csv(pair, "metric", "km", ["100000.204"])
            resp = await _post_csv(client, auth_headers, vin, pair, body)
            assert resp.status_code == 200, resp.text
            assert resp.json()["skipped_count"] == 1, resp.json()
            assert await _count(db_session, model, vin) == 1

    @pytest.mark.parametrize("pair", list(_CSV_PAIRS))
    async def test_imperial_csv_two_readings_in_one_file(
        self, client, auth_headers, test_user, db_session, pair
    ):
        """Both converted today with the same exact mile, so there is no drift between them."""
        model = _CSV_PAIRS[pair][0]
        async with _vehicle(db_session, test_user["id"], f"BANDICSV{pair.upper():0<9}") as vin:
            body = _csv(pair, "imperial", "mi", [FIRST_MI, SECOND_MI])
            resp = await _post_csv(client, auth_headers, vin, pair, body)
            assert resp.status_code == 200, resp.text
            assert resp.json()["success_count"] == 2, resp.json()
            assert await _count(db_session, model, vin) == 2

    @pytest.mark.parametrize(
        ("section", "model", "record"),
        [
            ("odometer_records", OdometerRecord, lambda km: {"odometer_km": km}),
            ("fuel_records", FuelRecord, lambda km: {"odometer_km": km, "liters": 40}),
            ("def_records", DEFRecord, lambda km: {"odometer_km": km, "liters": 9}),
            (
                "service_records",
                ServiceVisit,
                lambda km: {"odometer_km": km, "service_type": "Oil", "cost": 10},
            ),
        ],
    )
    async def test_metric_json_backup_two_readings(
        self, client, auth_headers, test_user, db_session, section, model, record
    ):
        async with _vehicle(
            db_session, test_user["id"], f"BANDJSON{section.split('_')[0].upper():0<9}"
        ) as vin:
            backup = {
                "export_version": "3",
                "units": "metric",
                section: [
                    {"date": "2026-03-01", **record(str(km))} for km in (FIRST_KM, SECOND_KM)
                ],
            }
            resp = await client.post(
                f"/api/import/vehicles/{vin}/json",
                headers=auth_headers,
                files={
                    "file": ("v3.json", BytesIO(json.dumps(backup).encode()), "application/json")
                },
                data={"skip_duplicates": "true"},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()[section]["success_count"] == 2, resp.json()
            assert await _count(db_session, model, vin) == 2

    @pytest.mark.parametrize(
        ("section", "pair"),
        [
            ("odometer_records", "odometer"),
            ("fuel_records", "fuel"),
            ("def_records", "def"),
            ("service_records", "service"),
        ],
    )
    async def test_metric_json_backup_reading_next_to_a_stored_one(
        self, client, auth_headers, test_user, db_session, section, pair
    ):
        """A v3 backup is canonical, so nothing in it was converted to drift."""
        model = _CSV_PAIRS[pair][0]
        record = {
            "odometer": {},
            "fuel": {"liters": 40},
            "def": {"liters": 9},
            "service": {"service_type": "Oil", "cost": 10},
        }[pair]
        async with _vehicle(db_session, test_user["id"], f"BANDJNXT{pair.upper():0<9}") as vin:
            db_session.add(_stored(pair, vin, FIRST_KM))
            await db_session.commit()
            backup = {
                "export_version": "3",
                "units": "metric",
                section: [{"date": "2026-03-01", "odometer_km": str(SECOND_KM), **record}],
            }
            resp = await client.post(
                f"/api/import/vehicles/{vin}/json",
                headers=auth_headers,
                files={
                    "file": ("v3.json", BytesIO(json.dumps(backup).encode()), "application/json")
                },
                data={"skip_duplicates": "true"},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()[section]["success_count"] == 1, resp.json()
            assert await _count(db_session, model, vin) == 2

    @pytest.mark.parametrize("pair", list(_CSV_PAIRS))
    async def test_imperial_csv_same_reading_twice_in_one_file(
        self, client, auth_headers, test_user, db_session, pair
    ):
        """The second copy is not a duplicate of the first: it was written by this import.

        Matching a stored row rounded to the column now belongs to
        `test_metric_csv_finer_than_the_column_matches_its_stored_rounding`.
        """
        assert converted_today("2008") == Decimal("3231.562752")
        model = _CSV_PAIRS[pair][0]
        async with _vehicle(db_session, test_user["id"], f"BANDTWCE{pair.upper():0<9}") as vin:
            body = _csv(pair, "imperial", "mi", ["2008", "2008"])
            resp = await _post_csv(client, auth_headers, vin, pair, body)
            assert resp.status_code == 200, resp.text
            # Both rows import: a row this import wrote is never a duplicate (T-14).
            assert resp.json()["success_count"] == 2, resp.json()
            assert resp.json()["skipped_count"] == 0, resp.json()
            # Two service rows of one day and odometer are one visit's two line items (G4-73).
            assert await _count(db_session, model, vin) == (1 if pair == "service" else 2)

    async def test_legacy_json_backup_two_readings(
        self, client, auth_headers, test_user, db_session
    ):
        """A v2 backup is converted from miles on ingest; both rows share today's factor."""
        async with _vehicle(db_session, test_user["id"], "BANDJSONLEGACY001") as vin:
            backup = {
                "odometer_records": [
                    {"date": "2026-03-01", "reading": miles} for miles in (FIRST_MI, SECOND_MI)
                ]
            }
            resp = await client.post(
                f"/api/import/vehicles/{vin}/json",
                headers=auth_headers,
                files={
                    "file": ("v2.json", BytesIO(json.dumps(backup).encode()), "application/json")
                },
                data={"skip_duplicates": "true"},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["odometer_records"]["success_count"] == 2, resp.json()
            assert await _count(db_session, OdometerRecord, vin) == 2

    async def test_fuelio_two_untimed_fillups_of_the_same_volume(
        self, client, auth_headers, test_user, db_session
    ):
        """No time and the same litres, so only the odometer tells them apart, and it does."""
        async with _vehicle(db_session, test_user["id"], "BANDFUELIO0000001") as vin:
            resp = await client.post(
                f"/api/import/vehicles/{vin}/fuel/fuelio",
                headers=auth_headers,
                files={
                    "file": (
                        "fuelio.csv",
                        "Date,Odometer,Liters,Price,Total cost\n"
                        f"2026-03-01,{FIRST_KM},40,1.50,60.00\n"
                        f"2026-03-01,{SECOND_KM},40,1.50,60.00\n",
                        "text/csv",
                    )
                },
                data={"skip_duplicates": "true", "odometer_unit": "km"},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["success_count"] == 2, resp.json()
            assert await _count(db_session, FuelRecord, vin) == 2

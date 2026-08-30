"""CSV schema v6: the importer reads the FILE's units, never a preference.

Issue #152 phase 2b, task 2. Per-quantity unit preferences mean a CSV can no
longer be described by one `metric`/`imperial` marker: a user whose distance
is miles but whose volume is litres produces a file that is neither. v6 lets
each unit-bearing column name its own unit with a phase-1 vocabulary token
(`Odometer (mi)`, `Volume (gal_uk)`), and this file pins that the importer
reads those tokens, still reads every older shape, and refuses rather than
guesses when a file is ambiguous.

An export bug shows a wrong number once. An import bug writes a wrong number
into canonical storage permanently, which is why every expected value below
is a hand-written literal computed from the documented factor by hand, never
routed back through the adapter under test.

Factors used, from `UnitConverter` (note these are the app's rounded
constants, not the exact SI definitions):
  MILES_TO_KM                 1.60934
  US_GALLONS_TO_LITERS        3.78541
  UK_GALLONS_TO_LITERS        4.54609
  US_MPG_TO_L100KM_NUMERATOR  235.214
  UK_MPG_TO_L100KM_NUMERATOR  282.481
  Fahrenheit                  (F - 32) * 5 / 9
"""

from __future__ import annotations

import ast
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.units import UNIT_FIELD_NAMES
from app.models.def_record import DEFRecord
from app.models.fuel import FuelRecord
from app.models.hours import HoursRecord
from app.models.odometer import OdometerRecord
from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit
from app.models.user import User
from app.models.vehicle import Vehicle

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def _reset_import_rate_limit():
    """Clear the shared import/export limiter storage between tests.

    `routes/import_data.py` has one module-level 20/minute limiter for every
    import endpoint; this file alone posts more than that. Mirrors the
    precedent in `test_import_data.py`.
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
    """A throwaway diesel vehicle, torn down in `finally`.

    The suite shares one database with no per-test rollback, so every row this
    file writes has to be removed explicitly or the next test's duplicate
    check sees it.
    """
    db_session.add(
        Vehicle(
            vin=vin,
            user_id=user_id,
            nickname=vin,
            vehicle_type="Car",
            year=2024,
            make="Test",
            model="V6Units",
            # Diesel so the DEF importer's fuel-type gate accepts the vehicle.
            fuel_type="diesel",
        )
    )
    await db_session.commit()
    try:
        yield vin
    finally:
        visit_ids = (
            (await db_session.execute(select(ServiceVisit.id).where(ServiceVisit.vin == vin)))
            .scalars()
            .all()
        )
        if visit_ids:
            await db_session.execute(
                delete(ServiceLineItem).where(ServiceLineItem.visit_id.in_(visit_ids))
            )
        for model in (ServiceVisit, FuelRecord, DEFRecord, OdometerRecord, HoursRecord):
            await db_session.execute(delete(model).where(model.vin == vin))
        await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
        await db_session.commit()


async def _post(client: AsyncClient, headers, vin: str, pair: str, body: str):
    """Upload one CSV to one importer, never skipping duplicates."""
    return await client.post(
        f"/api/import/vehicles/{vin}/{pair}/csv",
        headers=headers,
        files={"file": (f"{pair}.csv", BytesIO(body.encode()), "text/csv")},
        data={"skip_duplicates": "false"},
    )


async def _one(db_session: AsyncSession, model, vin: str):
    """The single row `model` holds for `vin`."""
    return (await db_session.execute(select(model).where(model.vin == vin))).scalars().one()


# --------------------------------------------------------------------------
# Per-consumer token parsing. One quantity per file, so a mutation to one
# consumer's call site fails that consumer's test and no other.
# --------------------------------------------------------------------------


class TestDistanceConsumers:
    """All four distance consumers read a v6 `(mi)` token.

    100 mi * 1.60934 = 160.934 km, stored into NUMERIC(10, 2) as 160.93.
    """

    async def test_service_distance_token(self, client, auth_headers, test_user, db_session):
        async with _vehicle(db_session, test_user["id"], "V6SVCDIST0000001") as vin:
            body = (
                "units_version,unit_system,Date,Category,Odometer (mi)\n"
                "6,custom,2026-03-01,Maintenance,100\n"
            )
            resp = await _post(client, auth_headers, vin, "service", body)
            assert resp.status_code == 200, resp.text
            assert resp.json()["success_count"] == 1
            visit = await _one(db_session, ServiceVisit, vin)
            assert float(visit.odometer_km) == pytest.approx(160.93, abs=0.01)

    async def test_fuel_distance_token(self, client, auth_headers, test_user, db_session):
        async with _vehicle(db_session, test_user["id"], "V6FUELDIST000001") as vin:
            body = "units_version,unit_system,Date,Odometer (mi)\n6,custom,2026-03-02,100\n"
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 200, resp.text
            record = await _one(db_session, FuelRecord, vin)
            assert float(record.odometer_km) == pytest.approx(160.93, abs=0.01)

    async def test_def_distance_token(self, client, auth_headers, test_user, db_session):
        async with _vehicle(db_session, test_user["id"], "V6DEFDIST0000001") as vin:
            body = "units_version,unit_system,Date,Odometer (mi)\n6,custom,2026-03-03,100\n"
            resp = await _post(client, auth_headers, vin, "def", body)
            assert resp.status_code == 200, resp.text
            record = await _one(db_session, DEFRecord, vin)
            assert float(record.odometer_km) == pytest.approx(160.93, abs=0.01)

    async def test_odometer_distance_token(self, client, auth_headers, test_user, db_session):
        async with _vehicle(db_session, test_user["id"], "V6ODODIST0000001") as vin:
            body = "units_version,unit_system,Date,Reading (mi)\n6,custom,2026-03-04,100\n"
            resp = await _post(client, auth_headers, vin, "odometer", body)
            assert resp.status_code == 200, resp.text
            record = await _one(db_session, OdometerRecord, vin)
            assert float(record.odometer_km) == pytest.approx(160.93, abs=0.01)


class TestVolumeConsumers:
    """Both volume consumers read a v6 volume token, flavour and all.

    10 gal_uk * 4.54609 = 45.4609 L. Reading the same cell as US gallons
    would store 37.8541 L, a permanent 20 percent loss.
    """

    async def test_fuel_volume_token(self, client, auth_headers, test_user, db_session):
        async with _vehicle(db_session, test_user["id"], "V6FUELVOL0000001") as vin:
            body = "units_version,unit_system,Date,Volume (gal_uk)\n6,custom,2026-03-05,10\n"
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 200, resp.text
            record = await _one(db_session, FuelRecord, vin)
            assert float(record.liters) == pytest.approx(45.461, abs=0.001)

    async def test_def_volume_token(self, client, auth_headers, test_user, db_session):
        async with _vehicle(db_session, test_user["id"], "V6DEFVOL00000001") as vin:
            body = "units_version,unit_system,Date,Volume (gal_uk)\n6,custom,2026-03-06,10\n"
            resp = await _post(client, auth_headers, vin, "def", body)
            assert resp.status_code == 200, resp.text
            record = await _one(db_session, DEFRecord, vin)
            assert float(record.liters) == pytest.approx(45.461, abs=0.001)


class TestPriceConsumers:
    """Both price consumers convert per the DENOMINATOR, not the volume factor.

    4.54609 per UK gallon is 1.000 per litre: the price is DIVIDED by the
    litres in a gallon. Multiplying instead would store 20.667 per litre.
    """

    async def test_fuel_price_token(self, client, auth_headers, test_user, db_session):
        async with _vehicle(db_session, test_user["id"], "V6FUELPRICE00001") as vin:
            body = (
                "units_version,unit_system,Date,Price Per Unit (gal_uk)\n"
                "6,custom,2026-03-07,4.54609\n"
            )
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 200, resp.text
            record = await _one(db_session, FuelRecord, vin)
            assert float(record.price_per_unit) == pytest.approx(1.000, abs=0.001)

    async def test_def_price_token(self, client, auth_headers, test_user, db_session):
        async with _vehicle(db_session, test_user["id"], "V6DEFPRICE000001") as vin:
            body = (
                "units_version,unit_system,Date,Price Per Unit (gal_uk)\n"
                "6,custom,2026-03-08,4.54609\n"
            )
            resp = await _post(client, auth_headers, vin, "def", body)
            assert resp.status_code == 200, resp.text
            record = await _one(db_session, DEFRecord, vin)
            assert float(record.price_per_unit) == pytest.approx(1.000, abs=0.001)


class TestDerivedFuelConsumers:
    """Temperature, consumption and speed: columns the exporter has always
    written and the importer silently dropped until this task."""

    async def test_fuel_temperature_token(self, client, auth_headers, test_user, db_session):
        """68 F = (68 - 32) * 5 / 9 = 20.0 C. Affine, not proportional."""
        async with _vehicle(db_session, test_user["id"], "V6FUELTEMP000001") as vin:
            body = "units_version,unit_system,Date,Outside Temp (f)\n6,custom,2026-03-09,68\n"
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 200, resp.text
            record = await _one(db_session, FuelRecord, vin)
            assert float(record.outside_temp_c) == pytest.approx(20.0, abs=0.05)

    async def test_fuel_consumption_token(self, client, auth_headers, test_user, db_session):
        """235.214 / 23.5214 US MPG = 10.00 L/100km. Reciprocal, not linear."""
        async with _vehicle(db_session, test_user["id"], "V6FUELCONS000001") as vin:
            body = (
                "units_version,unit_system,Date,OBC Economy (mpg_us)\n6,custom,2026-03-10,23.5214\n"
            )
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 200, resp.text
            record = await _one(db_session, FuelRecord, vin)
            assert float(record.obc_l_per_100km) == pytest.approx(10.00, abs=0.01)

    async def test_fuel_speed_token(self, client, auth_headers, test_user, db_session):
        """100 mph * 1.60934 = 160.934 km/h, stored into NUMERIC(5, 1)."""
        async with _vehicle(db_session, test_user["id"], "V6FUELSPEED00001") as vin:
            body = "units_version,unit_system,Date,OBC Avg Speed (mph)\n6,custom,2026-03-11,100\n"
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 200, resp.text
            record = await _one(db_session, FuelRecord, vin)
            assert float(record.obc_avg_speed_kmh) == pytest.approx(160.9, abs=0.05)


# --------------------------------------------------------------------------
# R4: resolution order is token, then marker, then version, then inference.
# --------------------------------------------------------------------------


class TestATokenlessDistanceColumnResolvesToKilometres:
    """The canonical-token table's DISTANCE cell, which nothing else can kill.

    `csv_units._CANONICAL_TOKEN[DISTANCE] = "km"` is the unit a distance
    column's values are already in when the FILE resolves metric and the
    column carries no token of its own. Mutating that one cell to `"mi"`
    passed the entire 3781-test backend suite byte-identically, while its
    three siblings (`VOLUME`, `PRICE_PER_VOLUME`, and `_IMPERIAL_TOKEN`'s
    distance entry) are killed by 12, 11 and 27 tests. This class exists to
    close that hole.

    The branch is live, not dead code. It runs for any file whose distance
    column is a TOKENLESS header (`Mileage`, bare `Reading`) and which
    resolves metric, either by an explicit `unit_system=metric` marker or by a
    `units_version` of 3 or more. Both are realistic: a hand-built sheet using
    the older column name, or a v5 export whose `unit_system` cell a
    spreadsheet blanked.

    Why the corpus cannot cover this. From v3 onward the service and odometer
    pairs' only unit-bearing column is `Odometer (km)` / `Reading (km)`, a
    TOKEN header, which R4 step 1 resolves before the file context is ever
    consulted. So `corpus[service-v3]`, `corpus[odometer-v3]` and
    `corpus[service-v4-premarker]` are metric-identity by construction: their
    expected value is their input value and no mutation of the unit tables can
    move them. A tokenless distance column under a metric file is the one
    shape that reaches the cell, and no fixture had one.

    What a regression would cost: a future tidy-up of that table multiplies
    every such odometer by 1.60934 on the way into canonical storage,
    permanently, with `bin/ci-check`, the compatibility corpus and the
    PostgreSQL suite all still green.
    """

    async def test_mileage_under_a_metric_marker_is_kilometres(
        self, client, auth_headers, test_user, db_session
    ):
        """`Mileage` names an imperial-era column but says nothing about its
        own unit, so the marker decides. 100 under `metric` is 100 km, NOT
        100 miles."""
        async with _vehicle(db_session, test_user["id"], "V6CANONMARK00001") as vin:
            body = "units_version,unit_system,Date,Mileage\n6,metric,2026-03-20,100\n"
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 200, resp.text
            record = await _one(db_session, FuelRecord, vin)
            assert record.odometer_km == Decimal("100.00")

    async def test_mileage_under_a_metric_version_is_kilometres(
        self, client, auth_headers, test_user, db_session
    ):
        """The other way in: no marker at all, `units_version=5`. R4 step 4
        reads 5 as metric canonical, and the tokenless column follows it.

        The SERVICE pair, so this also covers what `corpus[service-v3]`
        structurally cannot.
        """
        async with _vehicle(db_session, test_user["id"], "V6CANONVERS00001") as vin:
            body = "units_version,Date,Category,Description,Mileage\n5,2026-03-21,Maintenance,Oil,100\n"
            resp = await _post(client, auth_headers, vin, "service", body)
            assert resp.status_code == 200, resp.text
            visit = await _one(db_session, ServiceVisit, vin)
            assert visit.odometer_km == Decimal("100.00")

    async def test_a_bare_reading_under_a_metric_marker_is_kilometres(
        self, client, auth_headers, test_user, db_session
    ):
        """The ODOMETER pair's tokenless spelling, covering what
        `corpus[odometer-v3]` structurally cannot.

        Note the contrast with `test_bare_reading_with_no_marker_is_the_v2_
        odometer_shape`: the SAME header with no marker and no version is
        defined as miles (R9), and with a metric marker is kilometres. Both
        directions are now pinned, so neither can drift into the other.
        """
        async with _vehicle(db_session, test_user["id"], "V6CANONREAD00001") as vin:
            body = "units_version,unit_system,Date,Reading\n6,metric,2026-03-22,100\n"
            resp = await _post(client, auth_headers, vin, "odometer", body)
            assert resp.status_code == 200, resp.text
            record = await _one(db_session, OdometerRecord, vin)
            assert record.odometer_km == Decimal("100.00")


class TestResolutionOrder:
    async def test_token_beats_the_marker(self, client, auth_headers, test_user, db_session):
        """A `(mi)` token under a `metric` marker is still miles.

        The token describes ONE column; the marker describes the file. The
        more specific statement wins, which is the whole point of v6.
        """
        async with _vehicle(db_session, test_user["id"], "V6ORDTOKEN000001") as vin:
            body = "units_version,unit_system,Date,Odometer (mi)\n6,metric,2026-03-12,100\n"
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 200, resp.text
            record = await _one(db_session, FuelRecord, vin)
            assert float(record.odometer_km) == pytest.approx(160.93, abs=0.01)

    async def test_marker_beats_the_version(self, client, auth_headers, test_user, db_session):
        """`unit_system=imperial` wins over a v6 `units_version`.

        Version 6 alone would say metric-canonical. The marker says the values
        are imperial, and a tokenless `Liters` header has to believe it: 10
        US gallons is 37.8541 L.
        """
        async with _vehicle(db_session, test_user["id"], "V6ORDMARKER00001") as vin:
            body = "units_version,unit_system,Date,Liters\n6,imperial,2026-03-13,10\n"
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 200, resp.text
            record = await _one(db_session, FuelRecord, vin)
            assert float(record.liters) == pytest.approx(37.854, abs=0.001)

    async def test_version_beats_the_column_shape(
        self, client, auth_headers, test_user, db_session
    ):
        """`units_version=2` with no marker is imperial, whatever the columns say.

        `Liters` alone would otherwise infer metric. v2 predates metric
        canonical storage, so 10 there is 10 US gallons: 37.8541 L.
        """
        async with _vehicle(db_session, test_user["id"], "V6ORDVERSION0001") as vin:
            body = "units_version,Date,Liters\n2,2026-03-14,10\n"
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 200, resp.text
            record = await _one(db_session, FuelRecord, vin)
            assert float(record.liters) == pytest.approx(37.854, abs=0.001)

    async def test_column_shape_is_the_last_resort(
        self, client, auth_headers, test_user, db_session
    ):
        """No token, no marker, no version: `Mileage`/`Gallons` means imperial."""
        async with _vehicle(db_session, test_user["id"], "V6ORDSHAPE000001") as vin:
            body = "Date,Mileage,Gallons\n2026-03-15,100,10\n"
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 200, resp.text
            record = await _one(db_session, FuelRecord, vin)
            assert float(record.odometer_km) == pytest.approx(160.93, abs=0.01)
            assert float(record.liters) == pytest.approx(37.854, abs=0.001)

    async def test_a_future_version_is_not_an_error(
        self, client, auth_headers, test_user, db_session
    ):
        """`units_version=99` reads as metric canonical, not as a rejection.

        A newer file's unit-bearing columns carry tokens, which resolve
        without the version ever being consulted.
        """
        async with _vehicle(db_session, test_user["id"], "V6ORDFUTURE00001") as vin:
            body = "units_version,Date,Liters\n99,2026-03-16,10\n"
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 200, resp.text
            record = await _one(db_session, FuelRecord, vin)
            assert float(record.liters) == pytest.approx(10.0, abs=0.001)

    async def test_the_version_boundary_is_exactly_three(
        self, client, auth_headers, test_user, db_session
    ):
        """`units_version=3` is METRIC. v3 is the release that made canonical
        storage metric, so 3 is the first version that is not legacy imperial.

        The sibling above uses `2` and the one below `99`, so a threshold that
        slipped by one (`< 4`) would satisfy both. Only a fixture sitting ON
        the boundary constrains it, and until this test the boundary was
        pinned solely by two corpus cells whose ids advertise a file shape
        rather than the rule. 10 L stays 10 L; under `< 4` it would be read as
        10 US gallons and stored as 37.8541.
        """
        async with _vehicle(db_session, test_user["id"], "V6ORDVER3000001") as vin:
            body = "units_version,Date,Liters\n3,2026-03-18,10\n"
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 200, resp.text
            record = await _one(db_session, FuelRecord, vin)
            assert float(record.liters) == pytest.approx(10.0, abs=0.001)

    async def test_an_unparseable_version_reads_conservatively(
        self, client, auth_headers, test_user, db_session
    ):
        """A `units_version` we cannot parse falls back to imperial, as before."""
        async with _vehicle(db_session, test_user["id"], "V6ORDBADVER00001") as vin:
            body = "units_version,Date,Liters\nnonsense,2026-03-17,10\n"
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 200, resp.text
            record = await _one(db_session, FuelRecord, vin)
            assert float(record.liters) == pytest.approx(37.854, abs=0.001)


# --------------------------------------------------------------------------
# R8 rejection rules. Every one has a fixture and a user-visible error.
# --------------------------------------------------------------------------


class TestRejections:
    async def test_unrecognised_token(self, client, auth_headers, test_user, db_session):
        async with _vehicle(db_session, test_user["id"], "V6REJUNKNOWN0001") as vin:
            body = "units_version,unit_system,Date,Odometer (furlong)\n6,custom,2026-04-01,100\n"
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 400, resp.text
            detail = resp.json()["detail"]
            assert "Odometer (furlong)" in detail
            assert "furlong" in detail
            assert (
                await db_session.execute(select(FuelRecord).where(FuelRecord.vin == vin))
            ).scalars().first() is None

    async def test_recognised_token_for_the_wrong_quantity(
        self, client, auth_headers, test_user, db_session
    ):
        """`Odometer (gal_us)` resolves to a real adapter and must still fail.

        Global adapter membership is not validation: applying 3.78541 to a
        distance column is dimensionally meaningless and silently wrong.
        """
        async with _vehicle(db_session, test_user["id"], "V6REJWRONGQ00001") as vin:
            body = "units_version,unit_system,Date,Odometer (gal_us)\n6,custom,2026-04-02,100\n"
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 400, resp.text
            assert "distance" in resp.json()["detail"]

    async def test_volume_column_with_a_distance_token(
        self, client, auth_headers, test_user, db_session
    ):
        async with _vehicle(db_session, test_user["id"], "V6REJVOLMI000001") as vin:
            body = "units_version,unit_system,Date,Volume (mi)\n6,custom,2026-04-03,10\n"
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 400, resp.text
            assert "volume" in resp.json()["detail"]

    async def test_unrecognised_marker(self, client, auth_headers, test_user, db_session):
        """`imperial_ukk` used to import as US gallons. A typo must fail loudly."""
        async with _vehicle(db_session, test_user["id"], "V6REJMARKER00001") as vin:
            body = "units_version,unit_system,Date,Gallons\n5,imperial_ukk,2026-04-04,10\n"
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 400, resp.text
            assert "imperial_ukk" in resp.json()["detail"]

    async def test_custom_marker_with_a_tokenless_column(
        self, client, auth_headers, test_user, db_session
    ):
        """`custom` says the units are in the headers, so a bare `Liters` lies."""
        async with _vehicle(db_session, test_user["id"], "V6REJCUSTOM00001") as vin:
            body = "units_version,unit_system,Date,Liters\n6,custom,2026-04-05,10\n"
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 400, resp.text
            assert "Liters" in resp.json()["detail"]

    async def test_two_candidate_columns_for_one_quantity(
        self, client, auth_headers, test_user, db_session
    ):
        async with _vehicle(db_session, test_user["id"], "V6REJTWOCOL00001") as vin:
            body = (
                "units_version,unit_system,Date,Odometer (km),Mileage\n6,custom,2026-04-06,100,62\n"
            )
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 400, resp.text
            detail = resp.json()["detail"]
            assert "Odometer (km)" in detail and "Mileage" in detail

    async def test_duplicate_unit_column(self, client, auth_headers, test_user, db_session):
        async with _vehicle(db_session, test_user["id"], "V6REJDUPCOL00001") as vin:
            body = (
                "units_version,unit_system,Date,Odometer (mi),Odometer (mi)\n"
                "6,custom,2026-04-07,100,100\n"
            )
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 400, resp.text
            assert "duplicate" in resp.json()["detail"].lower()

    async def test_rows_disagreeing_about_unit_system(
        self, client, auth_headers, test_user, db_session
    ):
        """The marker is written into EVERY row, so later rows can disagree."""
        async with _vehicle(db_session, test_user["id"], "V6REJMIXMARK0001") as vin:
            body = (
                "units_version,unit_system,Date,Gallons\n"
                "5,metric,2026-04-08,10\n"
                "5,imperial,2026-04-09,10\n"
            )
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 400, resp.text
            assert "unit_system" in resp.json()["detail"]
            assert (
                await db_session.execute(select(FuelRecord).where(FuelRecord.vin == vin))
            ).scalars().first() is None

    async def test_rows_disagreeing_about_units_version(
        self, client, auth_headers, test_user, db_session
    ):
        async with _vehicle(db_session, test_user["id"], "V6REJMIXVER00001") as vin:
            body = "units_version,Date,Liters\n2,2026-04-10,10\n5,2026-04-11,10\n"
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 400, resp.text
            assert "units_version" in resp.json()["detail"]


# --------------------------------------------------------------------------
# R9: the compatibility guarantee and the exact rejection signature.
# --------------------------------------------------------------------------


class TestReportAmbiguity:
    REPORT_HEADER = "Date,Mileage,Category,Description,Cost,Vendor,Notes"
    V2_PRIMARY_HEADER = "Date,Category,Description,Mileage,Cost,Vendor,Notes"

    async def test_the_unversioned_service_report_is_rejected(
        self, client, auth_headers, test_user, db_session
    ):
        """Its `Mileage` was miles, then canonical km, under the same header."""
        async with _vehicle(db_session, test_user["id"], "V6REPORTREJ00001") as vin:
            body = f"{self.REPORT_HEADER}\n2026-04-12,100,Maintenance,Oil,10.00,Shop,\n"
            resp = await _post(client, auth_headers, vin, "service", body)
            assert resp.status_code == 400, resp.text
            assert "service-history report" in resp.json()["detail"]

    async def test_a_v2_primary_service_backup_still_imports(
        self, client, auth_headers, test_user, db_session
    ):
        """Same seven columns, different ORDER. Rejecting by membership would
        break every v2 backup restore, so the signature is the ordered tuple.

        100 mi * 1.60934 = 160.934 km.
        """
        async with _vehicle(db_session, test_user["id"], "V6V2PRIMARY00001") as vin:
            body = f"{self.V2_PRIMARY_HEADER}\n2026-04-13,Maintenance,Oil,100,10.00,Shop,\n"
            resp = await _post(client, auth_headers, vin, "service", body)
            assert resp.status_code == 200, resp.text
            assert resp.json()["success_count"] == 1
            visit = await _one(db_session, ServiceVisit, vin)
            assert float(visit.odometer_km) == pytest.approx(160.93, abs=0.01)

    async def test_bare_reading_with_no_marker_is_the_v2_odometer_shape(
        self, client, auth_headers, test_user, db_session
    ):
        """R9 states this rather than inferring it: bare `Reading` is MILES.

        The v2 standalone odometer export wrote miles under `Reading` with no
        marker and no version, and nothing in such a file distinguishes it
        from a metric sheet. 100 mi * 1.60934 = 160.934 km.
        """
        async with _vehicle(db_session, test_user["id"], "V6V2READING00001") as vin:
            body = "Date,Reading,Notes\n2026-04-14,100,v2 shape\n"
            resp = await _post(client, auth_headers, vin, "odometer", body)
            assert resp.status_code == 200, resp.text
            record = await _one(db_session, OdometerRecord, vin)
            assert float(record.odometer_km) == pytest.approx(160.93, abs=0.01)


# --------------------------------------------------------------------------
# Historical shapes still read correctly (the compatibility guarantee).
# --------------------------------------------------------------------------


class TestHistoricalShapes:
    async def test_v5_metric_fuel_shape(self, client, auth_headers, test_user, db_session):
        """Every value verbatim, including the three formerly dropped columns."""
        async with _vehicle(db_session, test_user["id"], "V6HISTMETRIC0001") as vin:
            body = (
                "units_version,unit_system,Date,Odometer (km),Liters,Price Per Liter,"
                "Outside Temp (C),OBC L/100km,OBC Avg Speed (km/h),OBC Trip Duration (s),"
                "SOC Start (%),Battery SOH (%)\n"
                "5,metric,2026-04-15,500,40,1.5,20,8,60,3600,10,99\n"
            )
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 200, resp.text
            record = await _one(db_session, FuelRecord, vin)
            assert float(record.odometer_km) == pytest.approx(500.0, abs=0.01)
            assert float(record.liters) == pytest.approx(40.0, abs=0.001)
            assert float(record.price_per_unit) == pytest.approx(1.5, abs=0.001)
            assert float(record.outside_temp_c) == pytest.approx(20.0, abs=0.05)
            assert float(record.obc_l_per_100km) == pytest.approx(8.0, abs=0.01)
            assert float(record.obc_avg_speed_kmh) == pytest.approx(60.0, abs=0.05)

    async def test_v5_us_imperial_fuel_shape(self, client, auth_headers, test_user, db_session):
        """The `imperial` marker settles every gallon-denominated column.

        100 mi -> 160.934 km; 10 US gal -> 37.8541 L; 3.78541 per US gal ->
        1.000 per L; 68 F -> 20.0 C; 235.214 / 23.5214 US MPG -> 10.00
        L/100km; 100 mph -> 160.934 km/h.
        """
        async with _vehicle(db_session, test_user["id"], "V6HISTUSIMP00001") as vin:
            body = (
                "units_version,unit_system,Date,Mileage,Gallons,Price Per Gallon,"
                "Outside Temp (F),OBC MPG,OBC Avg Speed (mph)\n"
                "5,imperial,2026-04-16,100,10,3.78541,68,23.5214,100\n"
            )
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 200, resp.text
            record = await _one(db_session, FuelRecord, vin)
            assert float(record.odometer_km) == pytest.approx(160.93, abs=0.01)
            assert float(record.liters) == pytest.approx(37.854, abs=0.001)
            assert float(record.price_per_unit) == pytest.approx(1.000, abs=0.001)
            assert float(record.outside_temp_c) == pytest.approx(20.0, abs=0.05)
            assert float(record.obc_l_per_100km) == pytest.approx(10.00, abs=0.01)
            assert float(record.obc_avg_speed_kmh) == pytest.approx(160.9, abs=0.05)

    async def test_v5_uk_imperial_fuel_shape(self, client, auth_headers, test_user, db_session):
        """`imperial_uk` picks the UK gallon AND the UK MPG numerator.

        10 UK gal -> 45.4609 L; 4.54609 per UK gal -> 1.000 per L;
        282.481 / 28.2481 UK MPG -> 10.00 L/100km.
        """
        async with _vehicle(db_session, test_user["id"], "V6HISTUKIMP00001") as vin:
            body = (
                "units_version,unit_system,Date,Mileage,Gallons,Price Per Gallon,OBC MPG\n"
                "5,imperial_uk,2026-04-17,100,10,4.54609,28.2481\n"
            )
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 200, resp.text
            record = await _one(db_session, FuelRecord, vin)
            assert float(record.liters) == pytest.approx(45.461, abs=0.001)
            assert float(record.price_per_unit) == pytest.approx(1.000, abs=0.001)
            assert float(record.obc_l_per_100km) == pytest.approx(10.00, abs=0.01)

    async def test_parenthesised_non_unit_headers_pass_through(
        self, client, auth_headers, test_user, db_session
    ):
        """`SOC Start (%)` and friends are not units and must not be parsed.

        A generic "whatever is in parentheses is a unit, unknown is an error"
        rule would reject every real v4/v5 fuel export.
        """
        async with _vehicle(db_session, test_user["id"], "V6PARENOK0000001") as vin:
            body = (
                "units_version,unit_system,Date,OBC Trip Duration (s),SOC Start (%),"
                "SOC End (%),Battery SOH (%)\n"
                "6,custom,2026-04-18,3600,10,90,99\n"
            )
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 200, resp.text
            assert resp.json()["success_count"] == 1

    async def test_price_slash_gal_alias_still_reads(
        self, client, auth_headers, test_user, db_session
    ):
        """`Price/Gal` is a third-party spelling the importer has always taken."""
        async with _vehicle(db_session, test_user["id"], "V6PRICESLASH0001") as vin:
            body = "Date,Mileage,Gallons,Price/Gal\n2026-04-19,100,10,3.78541\n"
            resp = await _post(client, auth_headers, vin, "fuel", body)
            assert resp.status_code == 200, resp.text
            record = await _one(db_session, FuelRecord, vin)
            assert float(record.price_per_unit) == pytest.approx(1.000, abs=0.001)


# --------------------------------------------------------------------------
# R1: the importer consults NO preference. Proven behaviourally.
# --------------------------------------------------------------------------


@pytest_asyncio.fixture
async def opposing_users(db_session: AsyncSession) -> dict[str, dict[str, object]]:
    """Two accounts with opposing unit preferences, including US vs UK gallons.

    A grep cannot prove R1: every importer already receives `current_user`, so
    `current_user.unit_distance` walks straight past one. Two accounts that
    disagree about every quantity in the file can.
    """
    hashed = (
        "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$"
        "hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
    )
    made: dict[str, dict[str, object]] = {}
    specs = {
        "uk_imperial": {
            "username": "v6unitsukuser",
            "unit_preference": "custom",
            "unit_distance": "mi",
            "unit_volume": "gal_uk",
            "unit_temperature": "f",
            "unit_consumption": "mpg_uk",
            "unit_speed": "mph",
            "secondary_gallon": "uk",
        },
        "us_metric": {
            "username": "v6unitsususer",
            "unit_preference": "metric",
            "unit_distance": "km",
            "unit_volume": "L",
            "unit_temperature": "c",
            "unit_consumption": "l_100km",
            "unit_speed": "kmh",
            "secondary_gallon": "us",
        },
    }
    for key, spec in specs.items():
        username = str(spec.pop("username"))
        existing = (
            await db_session.execute(select(User).where(User.username == username))
        ).scalar_one_or_none()
        if existing is None:
            existing = User(
                username=username,
                email=f"{username}@example.com",
                hashed_password=hashed,
                is_active=True,
                is_admin=False,
            )
            db_session.add(existing)
        for field, value in spec.items():
            setattr(existing, field, value)
        await db_session.commit()
        await db_session.refresh(existing)
        made[key] = {"id": existing.id, "username": existing.username}
    try:
        yield made
    finally:
        for entry in made.values():
            await db_session.execute(delete(User).where(User.id == entry["id"]))
        await db_session.commit()


def _headers_for(user: dict[str, object]) -> dict[str, str]:
    """Bearer headers for an arbitrary user id."""
    from app.services.auth import create_access_token

    token = create_access_token(data={"sub": str(user["id"]), "username": str(user["username"])})
    return {"Authorization": f"Bearer {token}"}


class TestImporterIgnoresPreferences:
    # One file, three unit-bearing sentinels. A distance-only file would prove
    # nothing about the gallon-flavour path, which is where the corruption
    # this rule exists for actually happened.
    SENTINEL_CSV = (
        "units_version,unit_system,Date,Mileage,Gallons,Price Per Gallon,Outside Temp (F)\n"
        "5,imperial,2026-05-01,100,10,3.78541,68\n"
    )

    async def test_the_same_file_imports_identically_under_opposing_preferences(
        self, client, db_session, opposing_users
    ):
        """Byte-identical file, opposing accounts, identical stored values.

        The marker says `imperial`, i.e. US gallons. A UK-preferring account
        must not turn 10 gallons into 45.4609 L: that is the exact defect that
        put inflated volumes into canonical storage permanently.
        """
        vins = {"uk_imperial": "V6PREFUKIMP00001", "us_metric": "V6PREFUSMET00001"}
        results: dict[str, tuple[float, float, float, float]] = {}
        for key, user in opposing_users.items():
            vin = vins[key]
            headers = _headers_for(user)
            async with _vehicle(db_session, user["id"], vin):
                resp = await _post(client, headers, vin, "fuel", self.SENTINEL_CSV)
                assert resp.status_code == 200, resp.text
                record = await _one(db_session, FuelRecord, vin)
                results[key] = (
                    float(record.odometer_km),
                    float(record.liters),
                    float(record.price_per_unit),
                    float(record.outside_temp_c),
                )

        # Hand-written literals, not a comparison of one run against the other:
        # two identically wrong imports would compare equal.
        for key, values in results.items():
            odometer, liters, price, temp = values
            assert odometer == pytest.approx(160.93, abs=0.01), key
            assert liters == pytest.approx(37.854, abs=0.001), key
            assert price == pytest.approx(1.000, abs=0.001), key
            assert temp == pytest.approx(20.0, abs=0.05), key
        assert results["uk_imperial"] == results["us_metric"]

    def test_the_csv_import_path_names_no_preference_source(self) -> None:
        """Secondary guard only. The behavioural test above is the proof.

        Catches the obvious reintroduction (calling `resolve_gallon_flavour`
        from the importer) but not `current_user.unit_volume`, which is why
        it is not the primary evidence.

        AST, not text: both modules DISCUSS `resolve_gallon_flavour` in prose
        explaining why they must not call it, and a substring scan would
        forbid saying so.
        """
        forbidden_calls = {
            "resolve_gallon_flavour",
            "render_context_for_request",
            "resolve_unit_set",
            "parse_default_unit_prefs",
        }
        forbidden_attrs = {"unit_preference", "secondary_gallon"} | {
            f"unit_{field}" for field in UNIT_FIELD_NAMES
        }
        backend = Path(__file__).resolve().parents[3]
        offenders: list[str] = []
        for relative in ("app/routes/import_data.py", "app/utils/csv_units.py"):
            tree = ast.parse((backend / relative).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id in forbidden_calls:
                    offenders.append(f"{relative}:{node.lineno} {node.id}")
                elif isinstance(node, ast.Attribute) and (
                    node.attr in forbidden_calls or node.attr in forbidden_attrs
                ):
                    offenders.append(f"{relative}:{node.lineno} .{node.attr}")
        assert not offenders, (
            "the CSV import path reads a unit PREFERENCE: "
            + ", ".join(offenders)
            + ". The unit must come from the file (see app/utils/csv_units.py)."
        )

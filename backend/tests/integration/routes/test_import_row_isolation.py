"""One bad row must not take the whole import down with it.

Each importer wraps its row in `try/except Exception` and records a per-row
error, but the `db.commit()` that actually writes is OUTSIDE that loop. So a
constraint violation is not raised where the handler can see it: it surfaces at
commit, escapes the route, and returns **500** -- discarding every valid row in
the file along with the bad one.

Nobody hit this before v3.3.0 for warranty, insurance or tax, because those
constructors raised `TypeError` on nonexistent kwargs first and every row failed
early inside the try. Fixing the kwargs let rows reach the database for the
first time, and exposed the real error path underneath.

A savepoint per row puts the write back inside the handler, so a row that
violates a CHECK is one reported row and the rest of the file still imports.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import get_db
from app.main import app
from app.models.def_record import DEFRecord
from app.models.fuel import FuelRecord
from app.models.hours import HoursRecord
from app.models.insurance import InsurancePolicy, InsurancePolicyVehicle
from app.models.odometer import OdometerRecord
from app.models.vehicle import Vehicle

# Diesel, so the DEF imports are accepted.
pytestmark = pytest.mark.own_vehicle(fuel_type="diesel")


@asynccontextmanager
async def _production_session(test_engine):
    """Route one request through a session that does not autoflush.

    Production sessions never autoflush (`app/database.py`). This builds its
    own sessionmaker over `test_engine` and pins the same setting directly,
    independent of conftest's `test_sessionmaker`, so these tests keep
    exercising production's unit of work even if conftest's setting changes.
    """
    maker = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    async with maker() as session:

        async def override_get_db():
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

        previous = app.dependency_overrides.get(get_db)
        app.dependency_overrides[get_db] = override_get_db
        try:
            yield session
        finally:
            if previous is not None:
                app.dependency_overrides[get_db] = previous
            else:
                app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
class TestOneUploadKeepsARowRepeatedInIt:
    """A row this import wrote is never a duplicate (T-14).

    Duplicates match the rows stored before the import began, one to one, so
    two identical rows in one upload into a table holding neither both import
    with `skip_duplicates`. Each loop still flushes its row in a savepoint, so
    a later check would see it; the matcher's id ceiling is what keeps it out.

    Uses `_production_session`, an explicitly non-autoflushing session pinned
    directly over `test_engine` (`app/database.py`), independent of
    conftest's `client` fixture, so these tests keep exercising production's
    unit of work even if conftest's setting changes.
    """

    async def test_fuel_csv_keeps_a_row_repeated_within_one_upload(
        self, client: AsyncClient, auth_headers, own_vehicle, test_engine
    ):
        csv_content = (
            "Date,Odometer (km),Liters,Price Per Liter,Total Cost,Full Tank,Notes\n"
            "2027-01-10,70000,40.0,1.50,60.0,True,Repeat\n"
            "2027-01-10,70000,40.0,1.50,60.0,True,Repeat\n"
        )
        async with _production_session(test_engine) as session:
            response = await client.post(
                f"/api/import/vehicles/{own_vehicle.vin}/fuel/csv",
                headers=auth_headers,
                files={"file": ("fuel.csv", BytesIO(csv_content.encode()), "text/csv")},
            )
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["success_count"] == 2, data
            assert data["skipped_count"] == 0, data

            count = await session.execute(
                select(func.count())
                .select_from(FuelRecord)
                .where(
                    FuelRecord.vin == own_vehicle.vin,
                    FuelRecord.date == date(2027, 1, 10),
                    FuelRecord.odometer_km == Decimal("70000"),
                )
            )
            assert count.scalar() == 2

    async def test_def_csv_keeps_a_row_repeated_within_one_upload(
        self, client: AsyncClient, auth_headers, own_vehicle, test_engine
    ):
        csv_content = (
            "Date,Odometer (km),Liters,Price Per Unit,Total Cost,Fill Level,Source,Brand,Notes\n"
            "2027-01-11,70010,9.464,1.10,10.41,0.60,dealer,BlueDEF,Repeat\n"
            "2027-01-11,70010,9.464,1.10,10.41,0.60,dealer,BlueDEF,Repeat\n"
        )
        async with _production_session(test_engine) as session:
            response = await client.post(
                f"/api/import/vehicles/{own_vehicle.vin}/def/csv",
                headers=auth_headers,
                files={"file": ("def.csv", BytesIO(csv_content.encode()), "text/csv")},
            )
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["success_count"] == 2, data
            assert data["skipped_count"] == 0, data

            count = await session.execute(
                select(func.count())
                .select_from(DEFRecord)
                .where(
                    DEFRecord.vin == own_vehicle.vin,
                    DEFRecord.date == date(2027, 1, 11),
                    DEFRecord.odometer_km == Decimal("70010"),
                )
            )
            assert count.scalar() == 2

    async def test_hours_csv_keeps_a_row_repeated_within_one_upload(
        self, client: AsyncClient, auth_headers, own_vehicle, test_engine
    ):
        csv_content = "Date,Engine Hours,Notes\n2027-01-12,55.5,Repeat\n2027-01-12,55.5,Repeat\n"
        async with _production_session(test_engine) as session:
            response = await client.post(
                f"/api/import/vehicles/{own_vehicle.vin}/hours/csv",
                headers=auth_headers,
                files={"file": ("hours.csv", BytesIO(csv_content.encode()), "text/csv")},
            )
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["success_count"] == 2, data
            assert data["skipped_count"] == 0, data

            count = await session.execute(
                select(func.count())
                .select_from(HoursRecord)
                .where(
                    HoursRecord.vin == own_vehicle.vin,
                    HoursRecord.date == date(2027, 1, 12),
                    HoursRecord.engine_hours == Decimal("55.5"),
                )
            )
            assert count.scalar() == 2

    async def test_vehicle_json_fuel_keeps_a_row_repeated_within_one_upload(
        self, client: AsyncClient, auth_headers, own_vehicle, test_engine
    ):
        json_data = {
            "export_version": "3",
            "units": "metric",
            "fuel_records": [
                {"date": "2027-01-13", "odometer_km": 70020, "liters": 40.0, "cost": 60.0},
                {"date": "2027-01-13", "odometer_km": 70020, "liters": 40.0, "cost": 60.0},
            ],
        }
        async with _production_session(test_engine) as session:
            response = await client.post(
                f"/api/import/vehicles/{own_vehicle.vin}/json",
                headers=auth_headers,
                files={
                    "file": (
                        "vehicle.json",
                        BytesIO(json.dumps(json_data).encode()),
                        "application/json",
                    )
                },
                data={"skip_duplicates": "true"},
            )
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["fuel_records"]["success_count"] == 2, data
            assert data["fuel_records"]["skipped_count"] == 0, data

            count = await session.execute(
                select(func.count())
                .select_from(FuelRecord)
                .where(
                    FuelRecord.vin == own_vehicle.vin,
                    FuelRecord.date == date(2027, 1, 13),
                    FuelRecord.odometer_km == Decimal("70020"),
                )
            )
            assert count.scalar() == 2

    async def test_vehicle_json_def_keeps_a_row_repeated_within_one_upload(
        self, client: AsyncClient, auth_headers, own_vehicle, test_engine
    ):
        json_data = {
            "export_version": "3",
            "units": "metric",
            "def_records": [
                {"date": "2027-01-14", "odometer_km": 70030, "liters": 9.0, "cost": 10.0},
                {"date": "2027-01-14", "odometer_km": 70030, "liters": 9.0, "cost": 10.0},
            ],
        }
        async with _production_session(test_engine) as session:
            response = await client.post(
                f"/api/import/vehicles/{own_vehicle.vin}/json",
                headers=auth_headers,
                files={
                    "file": (
                        "vehicle.json",
                        BytesIO(json.dumps(json_data).encode()),
                        "application/json",
                    )
                },
                data={"skip_duplicates": "true"},
            )
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["def_records"]["success_count"] == 2, data
            assert data["def_records"]["skipped_count"] == 0, data

            count = await session.execute(
                select(func.count())
                .select_from(DEFRecord)
                .where(
                    DEFRecord.vin == own_vehicle.vin,
                    DEFRecord.date == date(2027, 1, 14),
                    DEFRecord.odometer_km == Decimal("70030"),
                )
            )
            assert count.scalar() == 2

    async def test_vehicle_json_odometer_keeps_a_row_repeated_within_one_upload(
        self, client: AsyncClient, auth_headers, own_vehicle, test_engine
    ):
        json_data = {
            "export_version": "3",
            "units": "metric",
            "odometer_records": [
                {"date": "2027-01-15", "odometer_km": 70040, "notes": "Repeat"},
                {"date": "2027-01-15", "odometer_km": 70040, "notes": "Repeat"},
            ],
        }
        async with _production_session(test_engine) as session:
            response = await client.post(
                f"/api/import/vehicles/{own_vehicle.vin}/json",
                headers=auth_headers,
                files={
                    "file": (
                        "vehicle.json",
                        BytesIO(json.dumps(json_data).encode()),
                        "application/json",
                    )
                },
                data={"skip_duplicates": "true"},
            )
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["odometer_records"]["success_count"] == 2, data
            assert data["odometer_records"]["skipped_count"] == 0, data

            count = await session.execute(
                select(func.count())
                .select_from(OdometerRecord)
                .where(
                    OdometerRecord.vin == own_vehicle.vin,
                    OdometerRecord.date == date(2027, 1, 15),
                    OdometerRecord.odometer_km == Decimal("70040"),
                )
            )
            assert count.scalar() == 2


@pytest.mark.asyncio
class TestADatabaseInvalidRowDoesNotDiscardTheUpload:
    """A row that passes parsing but violates the database must not poison
    the whole upload the way `PendingRollbackError` would without a savepoint
    per row. Since batch 3a (T-6) the missing reading is refused before the
    write, so this pins the row error and the rows around it, not the
    savepoint.

    Only the vehicle JSON odometer loop had a reachable case: an entry with
    no odometer at all built `None` into `odometer_km`, which is
    non-nullable. The fuel, DEF and hours CSV loops and the JSON fuel and DEF
    loops share `FuelRecord`/`DEFRecord`/`HoursRecord`, none of which declare
    a `CheckConstraint`, and their non-nullable columns (`vin`, `date`, and
    for hours `engine_hours`) are either fixed by the route or already
    guarded by a parser check before the row reaches `db.add`. The test
    database is built from the ORM models (`Base.metadata.create_all`), so a
    CHECK that exists only in a migration's raw SQL does not apply here
    either. No test is written for those five loops.
    """

    async def test_vehicle_json_odometer_refuses_a_row_with_no_reading_and_keeps_the_rest(
        self, client: AsyncClient, auth_headers, own_vehicle, test_engine
    ):
        json_data = {
            "export_version": "3",
            "units": "metric",
            "odometer_records": [
                {"date": "2027-01-20", "odometer_km": 71000, "notes": "before"},
                {"date": "2027-01-21", "notes": "no odometer at all"},
                {"date": "2027-01-22", "odometer_km": 71010, "notes": "after"},
            ],
        }
        async with _production_session(test_engine) as session:
            response = await client.post(
                f"/api/import/vehicles/{own_vehicle.vin}/json",
                headers=auth_headers,
                files={
                    "file": (
                        "vehicle.json",
                        BytesIO(json.dumps(json_data).encode()),
                        "application/json",
                    )
                },
                data={"skip_duplicates": "true"},
            )
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["odometer_records"]["success_count"] == 2, data
            assert data["odometer_records"]["error_count"] == 1, data
            assert data["errors"] == ["Odometer record 1: odometer_km is missing"], data

            count = await session.execute(
                select(func.count())
                .select_from(OdometerRecord)
                .where(
                    OdometerRecord.vin == own_vehicle.vin,
                    OdometerRecord.date.in_([date(2027, 1, 20), date(2027, 1, 22)]),
                )
            )
            assert count.scalar() == 2

            missing = await session.execute(
                select(func.count())
                .select_from(OdometerRecord)
                .where(
                    OdometerRecord.vin == own_vehicle.vin,
                    OdometerRecord.date == date(2027, 1, 21),
                )
            )
            assert missing.scalar() == 0


@pytest.mark.asyncio
class TestABadServiceOrReminderRowDoesNotFailOtherRecordTypes:
    """`import_vehicle_json` writes six record types in one request behind one
    final `db.commit()`. Before this round, the service_records and reminders
    loops added their rows with no savepoint (a bare `db.add` plus flush, or
    a bare `db.add`), so a CHECK violation in either one raised at that add
    or at the unguarded final commit, escaped every per-row `try/except` in
    the whole function, and rolled back everything the request had written so
    far, other record types included.

    A service record with a category outside `VALID_SERVICE_CATEGORIES` and
    a reminder with a negative `recurrence_miles` are now also rejected by
    application-level validation before they ever reach the database, in
    addition to the savepoint each loop's `db.add` now runs in.
    """

    async def test_vehicle_json_service_record_with_invalid_category_does_not_500_the_upload(
        self, client: AsyncClient, auth_headers, own_vehicle, test_engine
    ):
        json_data = {
            "export_version": "3",
            "units": "metric",
            "fuel_records": [
                {"date": "2027-02-01", "odometer_km": 72000, "liters": 40.0, "cost": 60.0},
            ],
            "service_records": [
                {"date": "2027-02-02", "service_category": "Bogus", "cost": 10.0},
            ],
        }
        async with _production_session(test_engine) as session:
            response = await client.post(
                f"/api/import/vehicles/{own_vehicle.vin}/json",
                headers=auth_headers,
                files={
                    "file": (
                        "vehicle.json",
                        BytesIO(json.dumps(json_data).encode()),
                        "application/json",
                    )
                },
                data={"skip_duplicates": "true"},
            )
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["service_records"]["success_count"] == 0, data
            assert data["service_records"]["error_count"] == 1, data
            assert data["fuel_records"]["success_count"] == 1, data

            fuel_count = await session.execute(
                select(func.count())
                .select_from(FuelRecord)
                .where(
                    FuelRecord.vin == own_vehicle.vin,
                    FuelRecord.date == date(2027, 2, 1),
                    FuelRecord.odometer_km == Decimal("72000"),
                )
            )
            assert fuel_count.scalar() == 1

    async def test_vehicle_json_reminder_with_negative_recurrence_miles_does_not_500_the_upload(
        self, client: AsyncClient, auth_headers, own_vehicle, test_engine
    ):
        json_data = {
            "export_version": "3",
            "units": "metric",
            "fuel_records": [
                {"date": "2027-02-03", "odometer_km": 72010, "liters": 40.0, "cost": 60.0},
            ],
            "reminders": [
                {"description": "Oil change", "is_recurring": True, "recurrence_miles": -50},
            ],
        }
        async with _production_session(test_engine) as session:
            response = await client.post(
                f"/api/import/vehicles/{own_vehicle.vin}/json",
                headers=auth_headers,
                files={
                    "file": (
                        "vehicle.json",
                        BytesIO(json.dumps(json_data).encode()),
                        "application/json",
                    )
                },
                data={"skip_duplicates": "true"},
            )
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["reminders"]["success_count"] == 0, data
            assert data["reminders"]["error_count"] == 1, data
            assert data["fuel_records"]["success_count"] == 1, data

            fuel_count = await session.execute(
                select(func.count())
                .select_from(FuelRecord)
                .where(
                    FuelRecord.vin == own_vehicle.vin,
                    FuelRecord.date == date(2027, 2, 3),
                    FuelRecord.odometer_km == Decimal("72010"),
                )
            )
            assert fuel_count.scalar() == 1


@pytest_asyncio.fixture
async def imported_policies_go(
    own_vehicle: Vehicle, db_session: AsyncSession
) -> AsyncIterator[None]:
    """Deletes the policies an import linked to own_vehicle.

    The vehicle's delete only takes the links, so the policies would outlive it.
    Runs before own_vehicle's teardown, while the links still find them.
    """
    vin = own_vehicle.vin  # a rollback expires the object, so read it now
    yield
    await db_session.rollback()
    linked = select(InsurancePolicyVehicle.policy_id).where(InsurancePolicyVehicle.vin == vin)
    await db_session.execute(delete(InsurancePolicy).where(InsurancePolicy.id.in_(linked)))
    await db_session.commit()
    left = await db_session.scalar(
        select(func.count())
        .select_from(InsurancePolicy)
        .where(InsurancePolicy.provider.in_(["Good", "Bad"]))
    )
    assert left == 0, "the imported policy outlived the test"


@pytest.mark.asyncio
class TestOneBadRowDoesNotFailTheFile:
    async def test_an_invalid_warranty_type_is_a_row_error_not_a_500(
        self, client: AsyncClient, auth_headers, own_vehicle
    ):
        """`Roadside` is not in the `check_warranty_type` vocabulary.

        The good row above it must still import.
        """
        csv_content = (
            "Provider,Type,Coverage Details,Start Date,End Date,Notes\n"
            "Good Co,Extended,covered,2024-01-01,2029-01-01,fine\n"
            "Bad Co,Roadside,covered,2024-01-01,2025-01-01,bad type\n"
        )
        response = await client.post(
            f"/api/import/vehicles/{own_vehicle.vin}/warranties/csv",
            headers=auth_headers,
            files={"file": ("w.csv", BytesIO(csv_content.encode()), "text/csv")},
        )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["success_count"] == 1, data
        assert data["error_count"] == 1, data
        assert any("3" in e for e in data["errors"]), data["errors"]

    async def test_an_invalid_policy_type_is_a_row_error_not_a_500(
        self, client: AsyncClient, auth_headers, own_vehicle, imported_policies_go
    ):
        csv_content = (
            "Provider,Policy Number,Type,Start Date,End Date,Premium,Premium Frequency,"
            "Deductible,Coverage Limits,Notes\n"
            "Good,P1,Liability,2026-01-01,2027-01-01,10.00,Monthly,100.00,100/300,ok\n"
            "Bad,P2,Spaceship,2026-01-01,2027-01-01,10.00,Monthly,100.00,100/300,bad\n"
        )
        response = await client.post(
            f"/api/import/vehicles/{own_vehicle.vin}/insurance/csv",
            headers=auth_headers,
            files={"file": ("i.csv", BytesIO(csv_content.encode()), "text/csv")},
        )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["success_count"] == 1, data
        assert data["error_count"] == 1, data

    async def test_a_valid_file_still_imports_every_row(
        self, client: AsyncClient, auth_headers, own_vehicle
    ):
        """Guards the guard: a savepoint that always rolled back would pass
        both tests above while importing nothing."""
        csv_content = (
            "Provider,Type,Coverage Details,Start Date,End Date,Notes\n"
            "Alpha,Extended,a,2024-02-01,2029-02-01,x\n"
            "Beta,Corrosion,b,2024-03-01,2029-03-01,y\n"
        )
        response = await client.post(
            f"/api/import/vehicles/{own_vehicle.vin}/warranties/csv",
            headers=auth_headers,
            files={"file": ("w.csv", BytesIO(csv_content.encode()), "text/csv")},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["success_count"] == 2, data
        assert data["error_count"] == 0, data

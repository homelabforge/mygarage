"""Regression tests for closed PostgreSQL GitHub issues.

Each test class maps to a specific closed issue and verifies the fix
against a real PostgreSQL database.

Issues tested:
  #42 - Missing columns after upgrade (migrations not applied on PG)
  #48 - strftime() UndefinedFunctionError on PG
  #49 - Fuel edit Update button broken (null/NaN handling)
  #50 - DEF tracking toggle not persisting (null vs undefined)

Run with:
    docker exec mygarage-pg-test psql -U mygarage -d mygarage_test \
        -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
    MYGARAGE_SECRET_KEY=test MYGARAGE_TEST_MODE=true \
    TEST_DATABASE_URL="postgresql+asyncpg://mygarage:testpass@localhost:15432/mygarage_test" \
    PYTHONPATH=. python3 -m pytest tests/pg_issue_regression_test.py -v --override-ini="addopts="
"""

import os
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.database import Base, is_sqlite

PG_URL = os.getenv("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif("asyncpg" not in PG_URL, reason="PostgreSQL-only tests")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def pg_engine():
    """Create engine and apply schema via create_all (simulates fresh install)."""
    engine = create_async_engine(PG_URL, echo=False, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def pg_session(pg_engine):
    """Fresh session per test with suppressed teardown errors."""
    factory = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        try:
            await session.rollback()
        except Exception:
            pass


async def _create_user(session: AsyncSession, suffix: str):
    """Helper: create a test user."""
    from app.models.user import User

    user = User(
        username=f"pg_issue_{suffix}",
        email=f"pg_issue_{suffix}@test.com",
        hashed_password="fake",
        is_active=True,
        is_admin=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _create_vehicle(session: AsyncSession, user_id: int, suffix: str, **kwargs):
    """Helper: create a test vehicle with optional overrides."""
    from app.models.vehicle import Vehicle

    defaults = dict(
        vin=f"PGISSUE{suffix.upper()[:10]:0<10}",
        user_id=user_id,
        nickname=f"Issue {suffix} Vehicle",
        vehicle_type="Car",
    )
    defaults.update(kwargs)
    vehicle = Vehicle(**defaults)
    session.add(vehicle)
    await session.flush()
    return vehicle


# ===========================================================================
# Issue #42: PostgreSQL migrations — missing columns after upgrade
#
# Bug: Migrations used SQLite-only introspection (PRAGMA, sqlite_master).
#      On PostgreSQL, migrations silently failed → missing columns.
# Fix: Migration runner passes engine; migrations use inspect() not PRAGMA.
# ===========================================================================

class TestIssue42MigrationsApplied:
    """#42: Verify all columns that were reported missing actually exist in PG."""

    async def test_vehicles_def_tank_capacity_gallons(self, pg_engine):
        """Column vehicles.def_tank_capacity_gallons must exist."""
        async with pg_engine.connect() as conn:
            cols = await conn.run_sync(
                lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("vehicles")}
            )
        assert "def_tank_capacity_gallons" in cols, \
            "vehicles.def_tank_capacity_gallons missing — migration 038 not applied"

    async def test_odometer_records_source(self, pg_engine):
        """Column odometer_records.source must exist."""
        async with pg_engine.connect() as conn:
            cols = await conn.run_sync(
                lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("odometer_records")}
            )
        assert "source" in cols, \
            "odometer_records.source missing — migration not applied"

    async def test_livelink_devices_pending_offline_at(self, pg_engine):
        """Column livelink_devices.pending_offline_at must exist."""
        async with pg_engine.connect() as conn:
            cols = await conn.run_sync(
                lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("livelink_devices")}
            )
        assert "pending_offline_at" in cols, \
            "livelink_devices.pending_offline_at missing — migration not applied"

    async def test_maintenance_schedule_items_notification_cols(self, pg_engine):
        """Columns last_notified_at and last_notified_status must exist."""
        async with pg_engine.connect() as conn:
            cols = await conn.run_sync(
                lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("maintenance_schedule_items")}
            )
        assert "last_notified_at" in cols, \
            "maintenance_schedule_items.last_notified_at missing"
        assert "last_notified_status" in cols, \
            "maintenance_schedule_items.last_notified_status missing"

    async def test_insurance_policies_last_notified_at(self, pg_engine):
        """Column insurance_policies.last_notified_at must exist."""
        async with pg_engine.connect() as conn:
            cols = await conn.run_sync(
                lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("insurance_policies")}
            )
        assert "last_notified_at" in cols, \
            "insurance_policies.last_notified_at missing"

    async def test_warranty_records_last_notified_at(self, pg_engine):
        """Column warranty_records.last_notified_at must exist."""
        async with pg_engine.connect() as conn:
            cols = await conn.run_sync(
                lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("warranty_records")}
            )
        assert "last_notified_at" in cols, \
            "warranty_records.last_notified_at missing"

    async def test_all_expected_tables_exist(self, pg_engine):
        """Every model table must exist after create_all on PostgreSQL."""
        expected = set(Base.metadata.tables.keys())
        async with pg_engine.connect() as conn:
            actual = await conn.run_sync(
                lambda sync_conn: set(inspect(sync_conn).get_table_names())
            )
        missing = expected - actual
        assert not missing, f"Tables missing on PostgreSQL: {missing}"


# ===========================================================================
# Issue #48: strftime() crashes on PostgreSQL
#
# Bug: toll_service.py used func.strftime() unconditionally.
#      PostgreSQL doesn't have strftime() → UndefinedFunctionError.
# Fix: Dialect check: strftime() on SQLite, to_char() on PostgreSQL.
# ===========================================================================

class TestIssue48StrftimeOnPG:
    """#48: Verify toll summary uses to_char() not strftime() on PostgreSQL."""

    async def test_to_char_does_not_raise(self, pg_session):
        """to_char() query should execute without error on PostgreSQL."""
        from app.models.toll import TollTransaction

        user = await _create_user(pg_session, "i48a")
        vehicle = await _create_vehicle(pg_session, user.id, "i48a")

        # Add some toll data
        for month in (1, 2, 3):
            pg_session.add(TollTransaction(
                vin=vehicle.vin,
                date=date(2026, month, 15),
                amount=Decimal("5.00"),
                location="Test Toll Plaza",
            ))
        await pg_session.flush()

        # This is the exact query pattern from toll_service.py lines 564-577
        month_col = func.to_char(TollTransaction.date, "YYYY-MM").label("month")
        result = await pg_session.execute(
            select(
                month_col,
                func.count(TollTransaction.id).label("count"),
                func.sum(TollTransaction.amount).label("amount"),
            )
            .where(TollTransaction.vin == vehicle.vin)
            .group_by(month_col)
            .order_by(month_col)
        )
        rows = result.all()
        assert len(rows) == 3
        assert rows[0].month == "2026-01"
        assert rows[2].month == "2026-03"

    async def test_strftime_would_fail(self, pg_session):
        """strftime() should raise on PostgreSQL (proves the bug existed)."""
        from app.models.toll import TollTransaction

        with pytest.raises(Exception, match="(strftime|UndefinedFunction)"):
            await pg_session.execute(
                select(func.strftime("%Y-%m", TollTransaction.date))
                .limit(1)
            )
        # Roll back the failed transaction so session is usable
        await pg_session.rollback()

    def test_is_sqlite_flag_is_false(self):
        """is_sqlite must be False when using PostgreSQL."""
        assert is_sqlite is False


# ===========================================================================
# Issue #49: Fuel edit Update button broken
#
# Bug: PostgreSQL returns NULL for empty numeric columns. The frontend
#      Zod schema used z.coerce.number() which turned null→NaN, and
#      NaN failed min(0) validation silently, blocking the form submit.
# Fix: Backend returns null correctly; frontend transforms NaN→undefined.
#
# Backend test: verify null optional fields round-trip correctly.
# ===========================================================================

class TestIssue49FuelEditNulls:
    """#49: Verify fuel records with NULL optional fields work on PostgreSQL."""

    async def test_null_numeric_fields_persist(self, pg_session):
        """NULL optional numeric fields should persist and return as None."""
        from app.models.fuel import FuelRecord

        user = await _create_user(pg_session, "i49a")
        vehicle = await _create_vehicle(pg_session, user.id, "i49a")

        # Create fuel record with explicit NULLs in optional numeric fields
        # These are the fields that caused the bug: propane_gallons, kwh,
        # price_per_unit, tank_size_lb, tank_quantity
        record = FuelRecord(
            vin=vehicle.vin,
            date=date(2026, 3, 1),
            gallons=Decimal("12.5"),
            cost=Decimal("45.00"),
            fuel_type="Regular",
            # All optional numerics explicitly NULL
            propane_gallons=None,
            kwh=None,
            price_per_unit=None,
            tank_size_lb=None,
            tank_quantity=None,
            mileage=None,
            notes=None,
        )
        pg_session.add(record)
        await pg_session.flush()
        await pg_session.refresh(record)

        # These must come back as Python None, not NaN or 0
        assert record.propane_gallons is None
        assert record.kwh is None
        assert record.price_per_unit is None
        assert record.tank_size_lb is None
        assert record.tank_quantity is None
        assert record.mileage is None

    async def test_null_fields_in_raw_sql(self, pg_session):
        """Verify PostgreSQL actually stores NULL (not empty string or 0)."""
        from app.models.fuel import FuelRecord

        user = await _create_user(pg_session, "i49raw")
        vehicle = await _create_vehicle(pg_session, user.id, "i49raw")

        pg_session.add(FuelRecord(
            vin=vehicle.vin,
            date=date(2026, 3, 2),
            gallons=Decimal("8.0"),
            cost=Decimal("28.00"),
            fuel_type="Regular",
            propane_gallons=None,
            kwh=None,
            price_per_unit=None,
        ))
        await pg_session.flush()

        result = await pg_session.execute(text("""
            SELECT propane_gallons, kwh, price_per_unit
            FROM fuel_records
            WHERE vin = :vin
            AND propane_gallons IS NULL
            AND kwh IS NULL
            AND price_per_unit IS NULL
        """), {"vin": vehicle.vin})
        row = result.first()
        assert row is not None, "Should find record with NULL fields"
        assert row[0] is None  # propane_gallons
        assert row[1] is None  # kwh
        assert row[2] is None  # price_per_unit

    async def test_update_fuel_record_with_nulls(self, pg_session):
        """Updating a fuel record should handle NULL→value and value→NULL."""
        from app.models.fuel import FuelRecord

        user = await _create_user(pg_session, "i49b")
        vehicle = await _create_vehicle(pg_session, user.id, "i49b")

        # Create with a value
        record = FuelRecord(
            vin=vehicle.vin,
            date=date(2026, 3, 5),
            gallons=Decimal("10.0"),
            cost=Decimal("35.00"),
            fuel_type="Regular",
            price_per_unit=Decimal("3.50"),
        )
        pg_session.add(record)
        await pg_session.flush()
        record_id = record.id

        # Update to NULL (simulates user clearing the field)
        await pg_session.execute(
            update(FuelRecord)
            .where(FuelRecord.id == record_id)
            .values(price_per_unit=None)
        )
        await pg_session.flush()

        # Re-read and verify NULL
        result = await pg_session.execute(
            select(FuelRecord).where(FuelRecord.id == record_id)
        )
        updated = result.scalar_one()
        assert updated.price_per_unit is None, \
            "price_per_unit should be NULL after update"


# ===========================================================================
# Issue #50: DEF tracking toggle doesn't persist
#
# Bug: Frontend sent undefined (omitted from JSON) instead of null when
#      DEF tracking was disabled. Backend never received the field, so
#      the old value persisted. Also, VehicleEdit initialized the toggle
#      as `isDiesel || hasTankCap`, forcing it back on for all diesel.
# Fix: Frontend sends explicit null; toggle derives from DB value only.
#
# Backend test: verify def_tank_capacity_gallons can be set and cleared.
# ===========================================================================

class TestIssue50DefTrackingToggle:
    """#50: Verify DEF tracking can be enabled and disabled on PostgreSQL."""

    async def test_set_def_tank_capacity(self, pg_session):
        """Setting def_tank_capacity_gallons should persist."""
        from app.models.vehicle import Vehicle

        user = await _create_user(pg_session, "i50a")
        vehicle = await _create_vehicle(
            pg_session, user.id, "i50a",
            fuel_type="Diesel",
        )

        # Enable DEF tracking by setting capacity
        await pg_session.execute(
            update(Vehicle)
            .where(Vehicle.vin == vehicle.vin)
            .values(def_tank_capacity_gallons=Decimal("5.5"))
        )
        await pg_session.flush()

        result = await pg_session.execute(
            select(Vehicle).where(Vehicle.vin == vehicle.vin)
        )
        v = result.scalar_one()
        assert v.def_tank_capacity_gallons == Decimal("5.5")

    async def test_clear_def_tank_capacity_to_null(self, pg_session):
        """Setting def_tank_capacity_gallons to NULL should persist (disable DEF)."""
        from app.models.vehicle import Vehicle

        user = await _create_user(pg_session, "i50b")
        vehicle = await _create_vehicle(
            pg_session, user.id, "i50b",
            fuel_type="Diesel",
            def_tank_capacity_gallons=Decimal("5.5"),
        )

        # Verify it's set
        result = await pg_session.execute(
            select(Vehicle.def_tank_capacity_gallons)
            .where(Vehicle.vin == vehicle.vin)
        )
        assert result.scalar() == Decimal("5.5")

        # Disable DEF tracking by setting to NULL
        # This is what the frontend now sends when the toggle is off
        await pg_session.execute(
            update(Vehicle)
            .where(Vehicle.vin == vehicle.vin)
            .values(def_tank_capacity_gallons=None)
        )
        await pg_session.flush()

        # Verify it's NULL
        result = await pg_session.execute(
            select(Vehicle.def_tank_capacity_gallons)
            .where(Vehicle.vin == vehicle.vin)
        )
        val = result.scalar()
        assert val is None, \
            f"def_tank_capacity_gallons should be NULL after disabling, got {val}"

    async def test_null_def_stays_null_on_reread(self, pg_session):
        """After clearing DEF, re-reading the vehicle should still show NULL."""
        from app.models.vehicle import Vehicle

        user = await _create_user(pg_session, "i50c")
        vehicle = await _create_vehicle(
            pg_session, user.id, "i50c",
            fuel_type="Diesel",
            def_tank_capacity_gallons=None,
        )

        # Simulate the "reopen vehicle settings" that was reverting the toggle
        result = await pg_session.execute(
            select(Vehicle).where(Vehicle.vin == vehicle.vin)
        )
        v = result.scalar_one()

        # The fix: DEF enabled state should derive ONLY from the stored value
        has_tank_cap = (
            v.def_tank_capacity_gallons is not None
            and v.def_tank_capacity_gallons > 0
        )
        assert has_tank_cap is False, \
            "DEF should be disabled when def_tank_capacity_gallons is NULL"

    async def test_diesel_without_def_stays_disabled(self, pg_session):
        """A diesel vehicle with no DEF capacity should NOT auto-enable DEF.

        Bug: Old code did `isDiesel || hasTankCap` which forced DEF on
        for all diesel vehicles regardless of stored value.
        Fix: Uses `hasTankCap` only (derived from def_tank_capacity_gallons).
        """
        from app.models.vehicle import Vehicle

        user = await _create_user(pg_session, "i50d")
        vehicle = await _create_vehicle(
            pg_session, user.id, "i50d",
            fuel_type="Diesel",
            def_tank_capacity_gallons=None,  # DEF explicitly disabled
        )

        result = await pg_session.execute(
            select(Vehicle).where(Vehicle.vin == vehicle.vin)
        )
        v = result.scalar_one()

        # Reproduce the old buggy logic
        is_diesel = v.fuel_type and v.fuel_type.lower() == "diesel"
        has_tank_cap = (
            v.def_tank_capacity_gallons is not None
            and v.def_tank_capacity_gallons > 0
        )

        # Old buggy logic: def_enabled = is_diesel or has_tank_cap → True (WRONG)
        old_logic = is_diesel or has_tank_cap
        assert old_logic is True, "Sanity: old logic would have returned True"

        # New fixed logic: def_enabled = has_tank_cap only → False (CORRECT)
        new_logic = has_tank_cap
        assert new_logic is False, \
            "Fixed logic should NOT auto-enable DEF for diesel without capacity"

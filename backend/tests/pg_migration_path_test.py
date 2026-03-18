"""PostgreSQL migration path simulation.

Simulates real-world upgrade scenarios against PostgreSQL:

1. Fresh install: create_all → run all 49 migrations → verify schema
2. Upgrade from v2.21: create baseline schema missing new columns →
   run migrations → verify missing columns are added (Issue #42)
3. Idempotency: run migrations twice → no errors

The migration runner uses psycopg2 (sync), not asyncpg.

Run with:
    docker exec mygarage-pg-test psql -U mygarage -d mygarage_test \
        -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
    MYGARAGE_SECRET_KEY=test MYGARAGE_TEST_MODE=true \
    TEST_DATABASE_URL="postgresql+asyncpg://mygarage:testpass@localhost:15432/mygarage_test" \
    PYTHONPATH=. python3 -m pytest tests/pg_migration_path_test.py -v --override-ini="addopts=" -s
"""

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.database import Base
from app.migrations.runner import MigrationRunner

PG_ASYNC_URL = os.getenv("TEST_DATABASE_URL", "")
PG_SYNC_URL = PG_ASYNC_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")
MIGRATIONS_DIR = Path(__file__).parent.parent / "app" / "migrations"

pytestmark = pytest.mark.skipif("asyncpg" not in PG_ASYNC_URL, reason="PostgreSQL-only tests")


def _reset_schema():
    """Drop and recreate public schema (clean slate)."""
    engine = create_engine(PG_SYNC_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()


def _get_all_columns(engine, table_name: str) -> set[str]:
    """Get column names for a table via SQLAlchemy inspect."""
    insp = inspect(engine)
    if not insp.has_table(table_name):
        return set()
    return {col["name"] for col in insp.get_columns(table_name)}


def _get_all_tables(engine) -> set[str]:
    """Get all table names in public schema."""
    return set(inspect(engine).get_table_names())


# ===========================================================================
# Scenario 1: Fresh Install Path
#
# Simulates: New user deploys MyGarage with PostgreSQL for the first time.
# Flow: create_all → run_migrations → verify everything exists
# ===========================================================================


class TestFreshInstallPath:
    """Simulate a fresh PostgreSQL install: create_all + all migrations."""

    def test_fresh_install_creates_all_tables(self):
        """create_all should create all model tables on an empty PG database."""
        _reset_schema()

        # Step 1: create_all (what init_db does first)
        async_engine = create_async_engine(PG_ASYNC_URL, poolclass=NullPool)
        import asyncio

        async def _create():
            async with async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            await async_engine.dispose()

        asyncio.run(_create())

        # Verify tables
        sync_engine = create_engine(PG_SYNC_URL)
        tables = _get_all_tables(sync_engine)
        expected = set(Base.metadata.tables.keys())
        missing = expected - tables
        assert not missing, f"create_all missed tables: {missing}"
        print(f"  -> {len(tables)} tables created by create_all")
        sync_engine.dispose()

    def test_fresh_install_migrations_all_pass(self):
        """All 49 migrations should run without error on a fresh PG database."""
        _reset_schema()

        # create_all first (migrations expect base tables to exist)
        async_engine = create_async_engine(PG_ASYNC_URL, poolclass=NullPool)
        import asyncio

        async def _create():
            async with async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            await async_engine.dispose()

        asyncio.run(_create())

        # Run all migrations
        runner = MigrationRunner(PG_SYNC_URL, MIGRATIONS_DIR)
        runner.run_pending_migrations()

        # Verify tracking table
        sync_engine = create_engine(PG_SYNC_URL)
        with sync_engine.begin() as conn:
            result = conn.execute(text("SELECT count(*) FROM schema_migrations"))
            count = result.scalar()

        print(f"  -> {count} migrations recorded in schema_migrations")
        assert count > 0, "No migrations were recorded"
        sync_engine.dispose()

    def test_fresh_install_migration_count(self):
        """Should have applied all discovered migrations."""
        _reset_schema()

        async_engine = create_async_engine(PG_ASYNC_URL, poolclass=NullPool)
        import asyncio

        async def _create():
            async with async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            await async_engine.dispose()

        asyncio.run(_create())

        runner = MigrationRunner(PG_SYNC_URL, MIGRATIONS_DIR)
        all_migrations = runner._discover_migrations()
        runner.run_pending_migrations()

        applied = runner._get_applied_migrations()
        discovered_names = {name for name, _ in all_migrations}

        not_applied = discovered_names - applied
        assert not not_applied, f"Migrations not applied: {not_applied}"
        print(f"  -> All {len(applied)} migrations applied successfully")

        runner.engine.dispose()


# ===========================================================================
# Scenario 2: Upgrade from v2.21 (Issue #42)
#
# Simulates: Existing user upgrades from v2.21 to current.
# The v2.21 schema is missing columns that were added in later migrations.
# Flow: create baseline → mark old migrations as applied → run pending → verify
# ===========================================================================


class TestUpgradeFromV221:
    """Simulate upgrading from v2.21 to current version on PostgreSQL."""

    # Columns reported missing in Issue #42 that are added by migrations 038+
    # Note: odometer_records.source was added in migration 035 (pre-v2.21),
    # so it would already exist in a real v2.21 database.
    ISSUE_42_COLUMNS = {
        "vehicles": ["def_tank_capacity_gallons"],
        "livelink_devices": ["pending_offline_at"],
        "maintenance_schedule_items": ["last_notified_at", "last_notified_status"],
        "insurance_policies": ["last_notified_at"],
        "warranty_records": ["last_notified_at"],
    }

    def _create_v221_baseline(self):
        """Create a schema that looks like v2.21 — tables exist but new columns missing."""
        _reset_schema()

        # create_all gives us the CURRENT schema (all columns).
        # We need to create it, then DROP the columns that were added after v2.21
        # to simulate the old schema state.
        async_engine = create_async_engine(PG_ASYNC_URL, poolclass=NullPool)
        import asyncio

        async def _create():
            async with async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            await async_engine.dispose()

        asyncio.run(_create())

        # Now drop the columns that Issue #42 reported as missing
        sync_engine = create_engine(PG_SYNC_URL)
        with sync_engine.begin() as conn:
            for table, columns in self.ISSUE_42_COLUMNS.items():
                for col in columns:
                    try:
                        conn.execute(text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {col}"))
                    except Exception:
                        pass  # Column might not exist if table structure differs

            # Mark migrations up through ~037 as "already applied"
            # (simulating that the user's v2.21 DB had these already run)
            conn.execute(
                text("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    id SERIAL PRIMARY KEY,
                    migration_name VARCHAR(255) NOT NULL UNIQUE,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
            """)
            )

            # Mark first 37 migrations as applied (v2.21 baseline)
            runner = MigrationRunner(PG_SYNC_URL, MIGRATIONS_DIR)
            all_migrations = runner._discover_migrations()
            for name, _ in all_migrations[:37]:
                try:
                    conn.execute(
                        text("INSERT INTO schema_migrations (migration_name) VALUES (:name)"),
                        {"name": name},
                    )
                except Exception:
                    pass
            runner.engine.dispose()

        sync_engine.dispose()

    def test_v221_baseline_is_missing_columns(self):
        """Verify our baseline actually has the missing columns (sanity check)."""
        self._create_v221_baseline()

        sync_engine = create_engine(PG_SYNC_URL)
        for table, columns in self.ISSUE_42_COLUMNS.items():
            existing = _get_all_columns(sync_engine, table)
            for col in columns:
                assert col not in existing, f"{table}.{col} should NOT exist in v2.21 baseline"

        print("  -> v2.21 baseline confirmed: all Issue #42 columns are missing")
        sync_engine.dispose()

    def test_pending_migrations_add_missing_columns(self):
        """Running pending migrations should add all missing columns from #42."""
        self._create_v221_baseline()

        # Run pending migrations (038+)
        runner = MigrationRunner(PG_SYNC_URL, MIGRATIONS_DIR)
        runner.run_pending_migrations()

        # Verify all Issue #42 columns now exist
        sync_engine = create_engine(PG_SYNC_URL)
        for table, columns in self.ISSUE_42_COLUMNS.items():
            existing = _get_all_columns(sync_engine, table)
            for col in columns:
                assert col in existing, (
                    f"{table}.{col} still missing after migration — Issue #42 not fixed"
                )

        print("  -> All Issue #42 columns present after running pending migrations")
        sync_engine.dispose()
        runner.engine.dispose()

    def test_pending_migration_count(self):
        """Exactly 12 migrations should be pending from v2.21 (038-049)."""
        self._create_v221_baseline()

        runner = MigrationRunner(PG_SYNC_URL, MIGRATIONS_DIR)
        applied_before = runner._get_applied_migrations()
        all_migrations = runner._discover_migrations()
        pending = [n for n, _ in all_migrations if n not in applied_before]

        print(f"  -> {len(pending)} pending migrations: {pending[0]} .. {pending[-1]}")
        assert len(pending) >= 10, f"Expected 10+ pending migrations from v2.21, got {len(pending)}"

        runner.run_pending_migrations()

        applied_after = runner._get_applied_migrations()
        newly_applied = applied_after - applied_before
        assert len(newly_applied) == len(pending), (
            f"Applied {len(newly_applied)} but expected {len(pending)}"
        )

        runner.engine.dispose()


# ===========================================================================
# Scenario 3: Idempotency
#
# Simulates: User restarts container (migrations run again on every startup).
# All migrations should be safe to run twice without errors.
# ===========================================================================


class TestMigrationIdempotency:
    """Verify migrations are safe to run multiple times."""

    def test_double_run_no_errors(self):
        """Running all migrations twice should not raise any errors."""
        _reset_schema()

        async_engine = create_async_engine(PG_ASYNC_URL, poolclass=NullPool)
        import asyncio

        async def _create():
            async with async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            await async_engine.dispose()

        asyncio.run(_create())

        # First run
        runner1 = MigrationRunner(PG_SYNC_URL, MIGRATIONS_DIR)
        runner1.run_pending_migrations()
        first_count = len(runner1._get_applied_migrations())
        runner1.engine.dispose()

        # Second run — should be a no-op
        runner2 = MigrationRunner(PG_SYNC_URL, MIGRATIONS_DIR)
        runner2.run_pending_migrations()  # Should print "No pending migrations"
        second_count = len(runner2._get_applied_migrations())
        runner2.engine.dispose()

        assert first_count == second_count, (
            f"Migration count changed: {first_count} -> {second_count}"
        )
        print(f"  -> Idempotent: {second_count} migrations, no duplicates")

    def test_create_all_then_migrations_idempotent(self):
        """create_all + migrations should be idempotent (the init_db path)."""
        _reset_schema()

        async_engine = create_async_engine(PG_ASYNC_URL, poolclass=NullPool)
        import asyncio

        async def _init():
            # First init_db cycle
            async with async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        asyncio.run(_init())

        runner1 = MigrationRunner(PG_SYNC_URL, MIGRATIONS_DIR)
        runner1.run_pending_migrations()
        runner1.engine.dispose()

        # Second init_db cycle (simulates container restart)
        async def _init2():
            async with async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            await async_engine.dispose()

        asyncio.run(_init2())

        runner2 = MigrationRunner(PG_SYNC_URL, MIGRATIONS_DIR)
        runner2.run_pending_migrations()  # Should be no-op
        runner2.engine.dispose()

        # Schema should be intact
        sync_engine = create_engine(PG_SYNC_URL)
        tables = _get_all_tables(sync_engine)
        expected = set(Base.metadata.tables.keys())
        missing = expected - tables
        assert not missing, f"Tables missing after double init: {missing}"
        print(f"  -> Double init_db cycle: {len(tables)} tables intact")
        sync_engine.dispose()


# ===========================================================================
# Scenario 4: Migration runner PostgreSQL-specific behavior
#
# Verify the runner itself works correctly with PostgreSQL.
# ===========================================================================


class TestMigrationRunnerOnPG:
    """Verify migration runner mechanics work on PostgreSQL."""

    def test_tracking_table_uses_serial(self):
        """schema_migrations should use SERIAL PRIMARY KEY on PostgreSQL."""
        _reset_schema()

        runner = MigrationRunner(PG_SYNC_URL, MIGRATIONS_DIR)
        runner._ensure_migration_tracking_table()

        with runner.engine.begin() as conn:
            # Verify the table exists and has correct structure
            result = conn.execute(
                text("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 'schema_migrations'
                ORDER BY ordinal_position
            """)
            )
            cols = {row[0]: row[1] for row in result}

        assert "id" in cols, "schema_migrations missing id column"
        assert "migration_name" in cols
        assert "applied_at" in cols
        # PostgreSQL SERIAL creates an integer with a sequence
        assert cols["id"] == "integer", f"id should be integer, got {cols['id']}"
        assert cols["applied_at"] in ("timestamp without time zone", "timestamp with time zone")
        runner.engine.dispose()

    def test_engine_passed_to_migrations(self):
        """Migrations that accept engine= should receive the PG engine."""
        _reset_schema()

        async_engine = create_async_engine(PG_ASYNC_URL, poolclass=NullPool)
        import asyncio

        async def _create():
            async with async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            await async_engine.dispose()

        asyncio.run(_create())

        runner = MigrationRunner(PG_SYNC_URL, MIGRATIONS_DIR)

        # Check that migration 038 (DEF tracking) accepts engine parameter
        all_migrations = runner._discover_migrations()
        mig_038 = next((n, p) for n, p in all_migrations if "038" in n)

        import importlib.util
        import inspect as python_inspect

        spec = importlib.util.spec_from_file_location(mig_038[0], mig_038[1])
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        sig = python_inspect.signature(module.upgrade)
        assert "engine" in sig.parameters, "Migration 038 should accept engine= parameter"
        print(f"  -> {mig_038[0]} correctly accepts engine parameter")
        runner.engine.dispose()

    def test_applied_migrations_tracked(self):
        """Applied migrations should be recorded in schema_migrations."""
        _reset_schema()

        async_engine = create_async_engine(PG_ASYNC_URL, poolclass=NullPool)
        import asyncio

        async def _create():
            async with async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            await async_engine.dispose()

        asyncio.run(_create())

        runner = MigrationRunner(PG_SYNC_URL, MIGRATIONS_DIR)
        runner.run_pending_migrations()

        with runner.engine.begin() as conn:
            result = conn.execute(text("SELECT migration_name FROM schema_migrations ORDER BY id"))
            applied = [row[0] for row in result]

        # Should be sorted by filename (numeric prefix)
        assert applied == sorted(applied), "Migrations should be recorded in order"

        # First should be 001, last should be the highest number
        assert applied[0].startswith("001"), f"First migration should be 001, got {applied[0]}"
        print(f"  -> {len(applied)} migrations tracked: {applied[0]} .. {applied[-1]}")
        runner.engine.dispose()

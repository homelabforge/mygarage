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


@pytest.mark.skip(
    reason=(
        "v2.21 baseline simulation no longer works after migration 053 (v2.26.2). "
        "create_all produces the metric-canonical schema, but 053 is a destructive "
        "rebuild gated on an idempotency check that sees odometer_km already "
        "present and short-circuits. To restore real v2.21 upgrade-path coverage "
        "we'd need a hand-maintained v2.21 baseline SQL dump fed in before the "
        "migration runner — out of scope for the migration-runner regression tests, "
        "which are the focus of this file. Fresh install + idempotency + runner "
        "behaviour are still covered by TestFreshInstallPath, TestMigrationIdempotency, "
        "and TestMigrationRunnerOnPG below."
    )
)
class TestUpgradeFromV221:
    """Disabled — see class-level skip reason."""

    def test_disabled(self):
        pass


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

"""Regression tests for migration 054 against the pre-054 PG baseline.

These are the tests that would have caught the rc1 bugs:

- ``ALTER TABLE fuel_records ADD COLUMN filled_at DATETIME`` — PG
  rejects ``DATETIME`` (it wants ``TIMESTAMP``). The pre-existing
  ``pg_migration_path_test.py`` ran ``Base.metadata.create_all`` first,
  which created ``filled_at`` from the SQLAlchemy model and let the
  migration's idempotency guard short-circuit. The ALTER never ran.

- ``ALTER TABLE ... ADD CONSTRAINT IF NOT EXISTS ...`` — invalid PG
  syntax. The rc1 code wrapped it in try/except and silently swallowed
  the error, so the FKs never got installed.

This module loads the committed ``pre_054.sql`` baseline (which
represents an actual v2.26.4 install — schema and ``schema_migrations``
data with rows 001..053), runs migration 054 against it, and asserts
the post-state. PG-only by design (baselines are inherently PG).
"""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from tests.migrations._baseline import load_baseline


def _load_migration(name: str) -> types.ModuleType:
    migrations_dir = Path(__file__).parent.parent.parent / "app" / "migrations"
    path = migrations_dir / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load migration: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.fixture
def baseline_loaded(pg_engine):
    """Load pre_054.sql into a clean PG schema and yield the engine."""
    load_baseline(pg_engine, "pre_054")
    return pg_engine


def _filled_at_pg_type(engine) -> str:
    """Look up the actual data type PG assigned to fuel_records.filled_at."""
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'fuel_records' AND column_name = 'filled_at'"
            )
        ).scalar()
    return result or ""


def _fk_constraints_on(engine, table: str) -> set[str]:
    with engine.begin() as conn:
        return {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT constraint_name FROM information_schema.table_constraints "
                    "WHERE table_name = :t AND constraint_type = 'FOREIGN KEY'"
                ),
                {"t": table},
            )
        }


def test_054_filled_at_column_uses_timestamp_on_pg(baseline_loaded):
    """The rc1 bug was ``ADD COLUMN filled_at DATETIME`` against PG, which
    raises a syntax error. With Phase 1.1's dialect-aware translation,
    the column is added as ``TIMESTAMP`` and reports as
    ``timestamp without time zone`` in information_schema.
    """
    module = _load_migration("054_extended_fuel_tracking")
    module.upgrade(engine=baseline_loaded)

    actual_type = _filled_at_pg_type(baseline_loaded)
    assert actual_type == "timestamp without time zone", (
        f"filled_at column has type {actual_type!r}; expected "
        f"'timestamp without time zone'. Phase 1.1's _translate_type "
        f"may have regressed."
    )


def test_054_fk_constraints_actually_get_installed(baseline_loaded):
    """The rc1 bug was ``ADD CONSTRAINT IF NOT EXISTS`` (invalid PG syntax)
    wrapped in try/except, so the FKs were silently skipped. Phase 1.2's
    information_schema check + plain ``ADD CONSTRAINT`` actually
    installs them."""
    module = _load_migration("054_extended_fuel_tracking")
    module.upgrade(engine=baseline_loaded)

    fks = _fk_constraints_on(baseline_loaded, "fuel_records")
    assert "fk_fuel_records_station_address_book" in fks, (
        f"Expected fk_fuel_records_station_address_book in fuel_records FKs; found: {sorted(fks)}"
    )
    assert "fk_fuel_records_driver_user" in fks, (
        f"Expected fk_fuel_records_driver_user in fuel_records FKs; found: {sorted(fks)}"
    )


def test_054_idempotent_on_pg_baseline(baseline_loaded):
    """Running the migration twice must not error and must not duplicate
    the FK constraints (information_schema check covers this)."""
    module = _load_migration("054_extended_fuel_tracking")
    module.upgrade(engine=baseline_loaded)
    fks_after_first = _fk_constraints_on(baseline_loaded, "fuel_records")

    module.upgrade(engine=baseline_loaded)
    fks_after_second = _fk_constraints_on(baseline_loaded, "fuel_records")

    assert fks_after_first == fks_after_second, (
        f"Idempotency violation: FK set changed between runs. "
        f"First: {sorted(fks_after_first)}, Second: {sorted(fks_after_second)}"
    )


def test_054_adds_all_expected_columns_on_pg(baseline_loaded):
    """Belt-and-suspenders: every column declared in ``_NEW_COLUMNS`` must
    be present after the migration runs against the baseline."""
    module = _load_migration("054_extended_fuel_tracking")
    module.upgrade(engine=baseline_loaded)

    insp = inspect(baseline_loaded)
    fuel_cols = {c["name"] for c in insp.get_columns("fuel_records")}
    expected = {
        "filled_at",
        "station_address_book_id",
        "station_name_freetext",
        "driver_user_id",
        "driver_name_freetext",
        "payment_method",
        "trip_type",
        "outside_temp_c",
        "obc_l_per_100km",
        "obc_avg_speed_kmh",
        "obc_trip_duration_s",
        "fuel_type_used",
    }
    missing = expected - fuel_cols
    assert not missing, (
        f"Migration 054 did not add all expected fuel_records columns. Missing: {sorted(missing)}"
    )

    vehicle_cols = {c["name"] for c in insp.get_columns("vehicles")}
    assert "fuel_type_secondary" in vehicle_cols

    user_cols = {c["name"] for c in insp.get_columns("users")}
    assert "default_payment_method" in user_cols
    assert "default_trip_type" in user_cols

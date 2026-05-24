"""Verify ``baselines/pre_054.sql`` loads cleanly and represents the
post-053, pre-054 schema on PostgreSQL.

What we cover here is just the baseline mechanism — the dump loads, the
expected schema_migrations rows are present, and the columns migration
054 will add are NOT yet present. Migration 054's actual behavior
(types, constraints, backfill) is exercised in
``test_054_extended_fuel_tracking.py`` once Phase 1 lands the migration
fixes.

Skipped on SQLite (baselines are inherently PG).
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from tests.migrations._baseline import baseline_exists, load_baseline


def test_pre_054_baseline_file_is_committed():
    assert baseline_exists("pre_054"), (
        "baselines/pre_054.sql is missing — see baselines/README.md to regenerate."
    )


def test_pre_054_baseline_loads_into_clean_pg(pg_engine):
    """Loading the dump must succeed and leave the public schema populated."""
    load_baseline(pg_engine, "pre_054")

    insp = inspect(pg_engine)
    tables = set(insp.get_table_names(schema="public"))
    # Sanity: representative tables from across the v2.26.4 schema
    assert "vehicles" in tables
    assert "fuel_records" in tables
    assert "users" in tables
    assert "address_book" in tables
    assert "schema_migrations" in tables


def test_pre_054_baseline_marks_001_through_053_as_applied(pg_engine):
    """The dump bundles schema_migrations data so migration 054 starts as
    the only pending migration. Without this, the runner would replay
    every migration from 001 onward — slow and noisy in tests."""
    load_baseline(pg_engine, "pre_054")

    with pg_engine.begin() as conn:
        applied = {
            row[0] for row in conn.execute(text("SELECT migration_name FROM schema_migrations"))
        }

    assert len(applied) == 53, f"Expected 53 applied migrations, found {len(applied)}"
    assert "001_add_vin_fields" in applied
    assert "053_metric_canonical_units" in applied
    # Migration 054 is intentionally NOT in the baseline — it's what gets
    # applied on top in the per-migration tests.
    assert not any(name.startswith("054_") for name in applied)


def test_pre_054_baseline_has_no_extended_fuel_columns(pg_engine):
    """The columns migration 054 adds must NOT yet exist. This is the
    invariant that makes the baseline useful: when 054 runs against this
    state, its ``ALTER TABLE ADD COLUMN`` statements actually have to
    execute, which is how dialect bugs (DATETIME, ADD CONSTRAINT IF NOT
    EXISTS) get caught."""
    load_baseline(pg_engine, "pre_054")

    insp = inspect(pg_engine)
    fuel_cols = {col["name"] for col in insp.get_columns("fuel_records", schema="public")}
    vehicle_cols = {col["name"] for col in insp.get_columns("vehicles", schema="public")}
    user_cols = {col["name"] for col in insp.get_columns("users", schema="public")}

    # Sample of columns 054 is supposed to add — none should be present yet.
    for absent in (
        "filled_at",
        "station_address_book_id",
        "station_name_freetext",
        "driver_user_id",
        "payment_method",
        "obc_l_per_100km",
        "fuel_type_used",
    ):
        assert absent not in fuel_cols, f"{absent} should not exist in pre-054 baseline"

    assert "fuel_type_secondary" not in vehicle_cols
    assert "default_payment_method" not in user_cols
    assert "default_trip_type" not in user_cols

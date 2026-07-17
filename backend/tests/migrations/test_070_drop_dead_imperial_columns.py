"""Tests for migration 070 — drop dead legacy imperial columns.

Dead columns (superseded by metric-canonical equivalents in migration 053,
but never removed on the create_all-then-migrate fresh-install path):
  - fuel_records.propane_gallons, fuel_records.tank_size_lb
  - vehicles.fuel_economy_city, .fuel_economy_highway, .fuel_economy_combined,
    vehicles.last_milestone_notified

Guarded (R1-H1): a column holding non-NULL values is preserved, not dropped.
Runs on SQLite and PostgreSQL via ``engine_for_migration``.
"""

import importlib.util
from pathlib import Path

from sqlalchemy import inspect, text

import app.migrations as _m


def _load(name):
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MIGRATION = "070_drop_dead_imperial_columns"


def _create_tables(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("""
                CREATE TABLE fuel_records (
                    id INTEGER PRIMARY KEY,
                    vin VARCHAR(17),
                    liters NUMERIC(9,3),
                    propane_gallons NUMERIC(9,3),
                    tank_size_lb NUMERIC(6,2)
                )
            """)
        )
        conn.execute(
            text("""
                CREATE TABLE vehicles (
                    vin VARCHAR(17) PRIMARY KEY,
                    nickname VARCHAR(100),
                    fuel_economy_city_l_per_100km NUMERIC(5,2),
                    fuel_economy_city NUMERIC(5,2),
                    fuel_economy_highway NUMERIC(5,2),
                    fuel_economy_combined NUMERIC(5,2),
                    last_milestone_notified NUMERIC(10,2)
                )
            """)
        )


def _columns(engine, table) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def test_drops_empty_dead_columns(engine_for_migration):
    """(a) All dead columns NULL — every one gets dropped; kept columns remain."""
    _dialect, engine, _url = engine_for_migration
    _create_tables(engine)
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO fuel_records (id, vin, liters) VALUES (1, 'VIN000000000001', 10.5)")
        )
        conn.execute(
            text(
                "INSERT INTO vehicles (vin, nickname, fuel_economy_city_l_per_100km) "
                "VALUES ('VIN000000000001', 'Daily Driver', 8.5)"
            )
        )

    _load(MIGRATION).upgrade(engine=engine)

    fuel_cols = _columns(engine, "fuel_records")
    vehicle_cols = _columns(engine, "vehicles")

    assert "propane_gallons" not in fuel_cols
    assert "tank_size_lb" not in fuel_cols
    assert "liters" in fuel_cols, "kept column must survive"

    assert "fuel_economy_city" not in vehicle_cols
    assert "fuel_economy_highway" not in vehicle_cols
    assert "fuel_economy_combined" not in vehicle_cols
    assert "last_milestone_notified" not in vehicle_cols
    assert "nickname" in vehicle_cols, "kept column must survive"
    assert "fuel_economy_city_l_per_100km" in vehicle_cols, "metric replacement must survive"


def test_populated_column_is_preserved(engine_for_migration):
    """(b) R1-H1: a non-NULL value in one dead column preserves that column,
    while the still-empty dead columns on the same tables still drop."""
    _dialect, engine, _url = engine_for_migration
    _create_tables(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO fuel_records (id, vin, liters, propane_gallons) "
                "VALUES (1, 'VIN000000000001', 10.5, 5.0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO vehicles (vin, nickname, last_milestone_notified) "
                "VALUES ('VIN000000000001', 'Daily Driver', 45000.0)"
            )
        )

    _load(MIGRATION).upgrade(engine=engine)

    fuel_cols = _columns(engine, "fuel_records")
    vehicle_cols = _columns(engine, "vehicles")

    assert "propane_gallons" in fuel_cols, "populated column must NOT be dropped"
    assert "tank_size_lb" not in fuel_cols, "still-empty dead column must still drop"

    assert "last_milestone_notified" in vehicle_cols, "populated column must NOT be dropped"
    assert "fuel_economy_city" not in vehicle_cols, "still-empty dead column must still drop"
    assert "fuel_economy_highway" not in vehicle_cols, "still-empty dead column must still drop"
    assert "fuel_economy_combined" not in vehicle_cols, "still-empty dead column must still drop"


def test_idempotent_second_run(engine_for_migration):
    """(c) Second run is a no-op — no error, no change."""
    _dialect, engine, _url = engine_for_migration
    _create_tables(engine)
    migration = _load(MIGRATION)

    migration.upgrade(engine=engine)
    migration.upgrade(engine=engine)  # must not raise

    fuel_cols = _columns(engine, "fuel_records")
    vehicle_cols = _columns(engine, "vehicles")
    assert "propane_gallons" not in fuel_cols
    assert "tank_size_lb" not in fuel_cols
    assert "fuel_economy_city" not in vehicle_cols
    assert "last_milestone_notified" not in vehicle_cols


def test_columns_already_absent_is_noop(engine_for_migration):
    """(c) A table already missing the dead columns (fresh install shape) is a no-op."""
    _dialect, engine, _url = engine_for_migration
    with engine.begin() as conn:
        conn.execute(
            text("""
                CREATE TABLE fuel_records (
                    id INTEGER PRIMARY KEY,
                    vin VARCHAR(17),
                    liters NUMERIC(9,3)
                )
            """)
        )
        conn.execute(
            text("""
                CREATE TABLE vehicles (
                    vin VARCHAR(17) PRIMARY KEY,
                    nickname VARCHAR(100),
                    fuel_economy_city_l_per_100km NUMERIC(5,2)
                )
            """)
        )

    _load(MIGRATION).upgrade(engine=engine)  # must not raise

    assert _columns(engine, "fuel_records") == {"id", "vin", "liters"}
    assert _columns(engine, "vehicles") == {"vin", "nickname", "fuel_economy_city_l_per_100km"}


def test_missing_table_is_noop(engine_for_migration):
    """(c) Neither table exists at all — must not raise."""
    _dialect, engine, _url = engine_for_migration
    _load(MIGRATION).upgrade(engine=engine)  # must not raise
    assert not inspect(engine).has_table("fuel_records")
    assert not inspect(engine).has_table("vehicles")

"""Tests for migration 099 - vehicles.fuel_filter_part_number.

FATAL migration: the Vehicle ORM maps this column, so every vehicle SELECT
includes it and a silent skip would 500 all vehicle reads. Parameterized over
SQLite *and* PostgreSQL via the ``engine_for_migration`` fixture (PG runs skip
when ``TEST_DATABASE_URL`` is unset).
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


def _make_vehicles_table(engine):
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE vehicles (
                    vin VARCHAR(17) PRIMARY KEY,
                    nickname VARCHAR(80)
                )
                """
            )
        )


def test_099_adds_the_fuel_filter_column(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_vehicles_table(engine)

    _load("099_add_vehicle_fuel_filter").upgrade(engine)

    cols = {c["name"] for c in inspect(engine).get_columns("vehicles")}
    assert "fuel_filter_part_number" in cols


def test_099_is_idempotent(engine_for_migration):
    """Second run is a no-op - no raise, no duplicate column."""
    _dialect, engine, _url = engine_for_migration
    _make_vehicles_table(engine)
    mod = _load("099_add_vehicle_fuel_filter")
    mod.upgrade(engine)
    mod.upgrade(engine)
    cols = [c["name"] for c in inspect(engine).get_columns("vehicles")]
    assert cols.count("fuel_filter_part_number") == 1


def test_099_missing_table_skips(engine_for_migration):
    """Fresh DB without a vehicles table must skip, not raise."""
    _dialect, engine, _url = engine_for_migration
    _load("099_add_vehicle_fuel_filter").upgrade(engine)


def test_099_leaves_existing_rows_null(engine_for_migration):
    """An added spec column must not invent a value for vehicles that have none.

    A part number is a fact about a specific vehicle. Backfilling any default
    would assert a filter this instance has never been told about, and the card
    renders a spec only when it holds a value.
    """
    _dialect, engine, _url = engine_for_migration
    _make_vehicles_table(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO vehicles (vin, nickname) VALUES ('X', 'Ram')"))

    _load("099_add_vehicle_fuel_filter").upgrade(engine)

    with engine.connect() as conn:
        value = conn.execute(text("SELECT fuel_filter_part_number FROM vehicles")).scalar()
    assert value is None

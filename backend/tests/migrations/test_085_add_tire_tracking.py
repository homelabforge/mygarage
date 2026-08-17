"""Tests for migration 085 — tire tracking tables (#138).

FATAL migration: creates tires and tire_readings tables required by tire ORM.
Parameterized over SQLite *and* PostgreSQL via the ``engine_for_migration``
fixture (PG runs skip when ``TEST_DATABASE_URL`` is unset).
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
    """Minimal vehicles table for FK reference."""
    is_pg = engine.dialect.name == "postgresql"
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


def test_085_creates_tires_and_tire_readings_tables(engine_for_migration):
    """Both tables are created with correct schema."""
    _dialect, engine, _url = engine_for_migration
    _make_vehicles_table(engine)

    _load("085_add_tire_tracking").upgrade(engine)

    inspector = inspect(engine)
    assert inspector.has_table("tires")
    assert inspector.has_table("tire_readings")

    tire_cols = {col["name"] for col in inspector.get_columns("tires")}
    assert {"id", "vin", "position", "brand", "model_name", "size", "dot_code"}.issubset(tire_cols)
    assert {"installed_date", "tread_depth_mm", "pressure_kpa", "min_tread_mm"}.issubset(tire_cols)

    reading_cols = {col["name"] for col in inspector.get_columns("tire_readings")}
    assert {"id", "tire_id", "vin", "position", "recorded_at", "tread_depth_mm"}.issubset(reading_cols)


def test_085_creates_indexes(engine_for_migration):
    """Indexes on tires(vin), tire_readings(tire_id), tire_readings(vin)."""
    dialect, engine, _url = engine_for_migration
    _make_vehicles_table(engine)

    _load("085_add_tire_tracking").upgrade(engine)

    # Use raw SQL to check indexes - inspector may cache stale state
    with engine.connect() as conn:
        if dialect == "sqlite":
            result = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='index'")
            ).fetchall()
            index_names = {r[0] for r in result if r[0]}
        else:
            result = conn.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename IN ('tires', 'tire_readings')"
                )
            ).fetchall()
            index_names = {r[0] for r in result}

    assert "idx_tires_vin" in index_names
    assert "idx_tire_readings_tire" in index_names
    assert "idx_tire_readings_vin" in index_names


def test_085_is_idempotent(engine_for_migration):
    """Re-running must be a no-op — tables already exist."""
    _dialect, engine, _url = engine_for_migration
    _make_vehicles_table(engine)

    mod = _load("085_add_tire_tracking")
    mod.upgrade(engine)
    mod.upgrade(engine)

    inspector = inspect(engine)
    assert inspector.has_table("tires")
    assert inspector.has_table("tire_readings")


def test_085_skips_cleanly_when_vehicles_absent(engine_for_migration):
    """Early return when vehicles table doesn't exist."""
    _dialect, engine, _url = engine_for_migration

    _load("085_add_tire_tracking").upgrade(engine)

    inspector = inspect(engine)
    assert not inspector.has_table("tires")
    assert not inspector.has_table("tire_readings")


def test_085_unique_constraint_on_vin_position(engine_for_migration):
    """Unique constraint prevents duplicate vin+position."""
    _dialect, engine, _url = engine_for_migration
    _make_vehicles_table(engine)

    _load("085_add_tire_tracking").upgrade(engine)

    with engine.begin() as conn:
        conn.execute(text("INSERT INTO vehicles (vin) VALUES ('VIN00000000000001')"))
        conn.execute(
            text(
                """
                INSERT INTO tires (vin, position, brand) VALUES ('VIN00000000000001', 'FL', 'Michelin')
                """
            )
        )

    import pytest
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO tires (vin, position, brand) VALUES ('VIN00000000000001', 'FL', 'BFGoodrich')
                    """
                )
            )

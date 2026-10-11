"""Migration 126: the hour meter on tire mounts and readings (#217).

FATAL for migration 100's reason: the ORM maps all three columns, so a silent
skip would 500 every tire read. Runs on SQLite and PostgreSQL through
`engine_for_migration`.
"""

import importlib.util
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Numeric, inspect, text

import app.migrations as _m

_NAME = "126_add_tire_hours"


def _load():
    path = Path(_m.__file__).parent / f"{_NAME}.py"
    spec = importlib.util.spec_from_file_location(_NAME, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_tables(engine):
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE tire_mount_periods (id INTEGER PRIMARY KEY, "
                "tire_id INTEGER NOT NULL, position VARCHAR(10) NOT NULL, "
                "mounted_odometer_km NUMERIC(10, 2))"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE tire_readings (id INTEGER PRIMARY KEY, "
                "tire_id INTEGER NOT NULL, odometer_km NUMERIC(10, 2))"
            )
        )
        conn.execute(
            text(
                "INSERT INTO tire_mount_periods (id, tire_id, position, mounted_odometer_km) "
                "VALUES (1, 1, 'FL', 1000.00)"
            )
        )
        conn.execute(
            text("INSERT INTO tire_readings (id, tire_id, odometer_km) VALUES (1, 1, 1500.00)")
        )


def test_126_adds_three_nullable_tenth_columns(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    _load().upgrade(engine)
    inspector = inspect(engine)
    periods = {c["name"]: c for c in inspector.get_columns("tire_mount_periods")}
    readings = {c["name"]: c for c in inspector.get_columns("tire_readings")}
    for column in (periods["mounted_hours"], periods["dismounted_hours"], readings["engine_hours"]):
        assert column["nullable"] is True
        assert isinstance(column["type"], Numeric), column["type"]
        # The `hours_records.engine_hours` type, so a tire's figure and the
        # vehicle's row hold the same tenth.
        assert column["type"].scale == 1


def test_126_keeps_existing_rows_and_leaves_hours_unknown(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    _load().upgrade(engine)
    with engine.connect() as conn:
        odometer, mounted, dismounted = conn.execute(
            text(
                "SELECT mounted_odometer_km, mounted_hours, dismounted_hours "
                "FROM tire_mount_periods WHERE id = 1"
            )
        ).one()
        engine_hours = conn.execute(
            text("SELECT engine_hours FROM tire_readings WHERE id = 1")
        ).scalar()
    assert Decimal(str(odometer)) == Decimal("1000")
    assert (mounted, dismounted, engine_hours) == (None, None, None)


def test_126_round_trips_a_tenth(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    _load().upgrade(engine)
    with engine.begin() as conn:
        conn.execute(text("UPDATE tire_mount_periods SET mounted_hours = 812.4 WHERE id = 1"))
        stored = conn.execute(
            text("SELECT mounted_hours FROM tire_mount_periods WHERE id = 1")
        ).scalar()
    assert Decimal(str(stored)) == Decimal("812.4")


def test_126_is_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    mod = _load()
    mod.upgrade(engine)
    mod.upgrade(engine)
    inspector = inspect(engine)
    period_cols = [c["name"] for c in inspector.get_columns("tire_mount_periods")]
    reading_cols = [c["name"] for c in inspector.get_columns("tire_readings")]
    assert period_cols.count("mounted_hours") == 1
    assert period_cols.count("dismounted_hours") == 1
    assert reading_cols.count("engine_hours") == 1


def test_126_missing_tables_skip(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _load().upgrade(engine)


def test_126_is_fatal():
    assert _load().FATAL is True

"""Tests for migration 086 — EV charge session fields on fuel_records (#138).

FATAL migration: adds soc_start_pct, soc_end_pct, charge_level, charge_location,
and battery_soh_pct columns required by FuelRecord ORM for EV/PHEV sessions.
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


def _make_fuel_records_table(engine):
    """Minimal post-053 fuel_records: the base columns before 086."""
    is_pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                CREATE TABLE fuel_records (
                    id {pk},
                    vin VARCHAR(17) NOT NULL,
                    date DATE,
                    liters NUMERIC(9,3),
                    kwh NUMERIC(8,3),
                    cost NUMERIC(9,2),
                    fuel_type_used VARCHAR(20)
                )
                """
            )
        )


def test_086_adds_ev_charge_columns(engine_for_migration):
    """All five EV session columns are added."""
    _dialect, engine, _url = engine_for_migration
    _make_fuel_records_table(engine)

    _load("086_add_ev_charge_session_fields").upgrade(engine)

    inspector = inspect(engine)
    cols = {col["name"] for col in inspector.get_columns("fuel_records")}

    assert "soc_start_pct" in cols
    assert "soc_end_pct" in cols
    assert "charge_level" in cols
    assert "charge_location" in cols
    assert "battery_soh_pct" in cols


def test_086_is_idempotent(engine_for_migration):
    """Re-running must be a no-op — columns already exist."""
    _dialect, engine, _url = engine_for_migration
    _make_fuel_records_table(engine)

    mod = _load("086_add_ev_charge_session_fields")
    mod.upgrade(engine)

    inspector = inspect(engine)
    cols_before = {col["name"] for col in inspector.get_columns("fuel_records")}

    mod.upgrade(engine)

    cols_after = {col["name"] for col in inspector.get_columns("fuel_records")}
    assert cols_before == cols_after


def test_086_skips_cleanly_when_fuel_records_absent(engine_for_migration):
    """Early return when fuel_records table doesn't exist."""
    _dialect, engine, _url = engine_for_migration

    _load("086_add_ev_charge_session_fields").upgrade(engine)


def test_086_columns_accept_decimal_values(engine_for_migration):
    """SOC and SOH columns store decimals correctly."""
    _dialect, engine, _url = engine_for_migration
    _make_fuel_records_table(engine)

    _load("086_add_ev_charge_session_fields").upgrade(engine)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO fuel_records
                    (vin, kwh, soc_start_pct, soc_end_pct, charge_level, charge_location, battery_soh_pct)
                VALUES
                    ('VIN00000000000001', 45.5, 20.5, 85.0, 'L2', 'home', 98.5)
                """
            )
        )
        row = conn.execute(
            text("SELECT soc_start_pct, soc_end_pct, battery_soh_pct FROM fuel_records")
        ).fetchone()

    assert float(row[0]) == 20.5
    assert float(row[1]) == 85.0
    assert float(row[2]) == 98.5

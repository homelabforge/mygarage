"""Tests for migration 094 — vehicle maintenance-spec columns.

FATAL migration: adds oil/torque/fluid columns required by the Vehicle ORM.
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


def test_094_adds_maintenance_spec_columns(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_vehicles_table(engine)

    _load("094_add_vehicle_maintenance_specs").upgrade(engine)

    cols = {c["name"] for c in inspect(engine).get_columns("vehicles")}
    assert {
        "oil_viscosity",
        "oil_capacity_liters",
        "oil_filter_part_number",
        "lug_nut_torque_nm",
        "coolant_type",
        "brake_fluid_type",
        "transmission_fluid_type",
        "maintenance_specs_notes",
    }.issubset(cols)


def test_094_is_idempotent(engine_for_migration):
    """Second run is a no-op — no raise, no duplicate columns."""
    _dialect, engine, _url = engine_for_migration
    _make_vehicles_table(engine)
    mod = _load("094_add_vehicle_maintenance_specs")
    mod.upgrade(engine)
    mod.upgrade(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("vehicles")}
    assert "oil_viscosity" in cols


def test_094_missing_table_skips(engine_for_migration):
    """Fresh DB without vehicles table → migration must skip, not raise."""
    _dialect, engine, _url = engine_for_migration
    _load("094_add_vehicle_maintenance_specs").upgrade(engine)

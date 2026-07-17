"""Tests for migration 069 — location_points table (Torque GPS breadcrumbs, #118).

Parameterized over SQLite *and* PostgreSQL via the ``engine_for_migration``
fixture (PG runs skip when ``TEST_DATABASE_URL`` is unset).

``vehicles``/``drive_sessions`` are pre-created because location_points'
FOREIGN KEY targets must already exist on PostgreSQL at CREATE TABLE time
(unlike SQLite, which does not validate FK target existence until DML with
``PRAGMA foreign_keys=ON``).
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


def _make_deps(engine):
    """Create minimal vehicles + drive_sessions tables for the FK targets."""
    is_pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY)"))
        conn.execute(text(f"CREATE TABLE drive_sessions (id {pk}, vin VARCHAR(17) NOT NULL)"))


def test_069_creates_table(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_deps(engine)
    _load("069_location_points").upgrade(engine)
    insp = inspect(engine)
    assert insp.has_table("location_points")
    cols = {c["name"] for c in insp.get_columns("location_points")}
    assert {
        "vin",
        "drive_session_id",
        "source",
        "timestamp",
        "latitude",
        "longitude",
        "speed",
        "heading",
        "altitude",
        "received_at",
    } <= cols
    index_names = {ix["name"] for ix in insp.get_indexes("location_points")}
    assert "idx_location_points_vin_time" in index_names


def test_069_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_deps(engine)
    mod = _load("069_location_points")
    mod.upgrade(engine)
    mod.upgrade(engine)
    assert inspect(engine).has_table("location_points")

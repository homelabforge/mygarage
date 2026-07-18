"""Tests for migration 073 — Torque device kind/torque_device_id + drive_session
external_session_id columns.

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


def _make_tables(engine):
    is_pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    with engine.begin() as conn:
        conn.execute(
            text(f"CREATE TABLE livelink_devices (id {pk}, device_id VARCHAR(20) UNIQUE NOT NULL)")
        )
        # device_id must exist pre-migration — the unique index is on (device_id, external_session_id).
        conn.execute(
            text(
                f"CREATE TABLE drive_sessions (id {pk}, vin VARCHAR(17) NOT NULL, device_id VARCHAR(20))"
            )
        )


def test_073_adds_columns(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO livelink_devices (device_id) VALUES ('abc123')"))
    _load("073_torque_device_columns").upgrade(engine)
    insp = inspect(engine)
    dev_cols = {c["name"] for c in insp.get_columns("livelink_devices")}
    assert {"kind", "torque_device_id"} <= dev_cols
    assert "external_session_id" in {c["name"] for c in insp.get_columns("drive_sessions")}
    ds_indexes = {ix["name"] for ix in insp.get_indexes("drive_sessions")}
    assert "uq_drive_session_external" in ds_indexes
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT kind FROM livelink_devices WHERE device_id='abc123'")
        ).first()
    assert row[0] == "wican"


def test_073_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    mod = _load("073_torque_device_columns")
    mod.upgrade(engine)
    mod.upgrade(engine)
    cols = [c["name"] for c in inspect(engine).get_columns("livelink_devices")]
    assert cols.count("kind") == 1 and cols.count("torque_device_id") == 1


def test_073_missing_table_skips(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _load("073_torque_device_columns").upgrade(engine)  # no tables → must not raise

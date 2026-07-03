"""Tests for migration 060 — drop dead feature tables (tsbs, vincario_*).

Why the migration exists: ``tsbs`` still declared an FK to
``service_records``, a table dropped by migration 040. With SQLite FK
enforcement now ON (v2.30.1), any DML against a child of a missing parent
raises "foreign key mismatch" — the dead DDL became a live landmine.

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


MIGRATION = "060_drop_dead_feature_tables"


def _create_dead_tables(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE tsbs (id INTEGER PRIMARY KEY, vin VARCHAR)"))
        conn.execute(text("CREATE TABLE vincario_cache (id INTEGER PRIMARY KEY, vin VARCHAR)"))
        conn.execute(text("CREATE TABLE vincario_credits (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE vincario_usage_log (id INTEGER PRIMARY KEY)"))


def test_drops_empty_dead_tables(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _create_dead_tables(engine)

    _load(MIGRATION).upgrade(engine=engine)

    remaining = set(inspect(engine).get_table_names())
    for table in ("tsbs", "vincario_cache", "vincario_credits", "vincario_usage_log"):
        assert table not in remaining, f"{table} should have been dropped"


def test_populated_table_is_left_alone(engine_for_migration):
    """Fail-safe: a dead table with rows is preserved for manual review."""
    _dialect, engine, _url = engine_for_migration
    _create_dead_tables(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO tsbs (id, vin) VALUES (1, 'SOMEVIN0000000001')"))

    _load(MIGRATION).upgrade(engine=engine)

    remaining = set(inspect(engine).get_table_names())
    assert "tsbs" in remaining, "populated table must NOT be dropped"
    assert "vincario_cache" not in remaining, "empty tables still get dropped"


def test_idempotent_when_tables_absent(engine_for_migration):
    """Second run (or a fresh install that never had the tables) is a no-op."""
    _dialect, engine, _url = engine_for_migration
    _create_dead_tables(engine)
    migration = _load(MIGRATION)

    migration.upgrade(engine=engine)
    migration.upgrade(engine=engine)  # must not raise

    remaining = set(inspect(engine).get_table_names())
    assert "tsbs" not in remaining

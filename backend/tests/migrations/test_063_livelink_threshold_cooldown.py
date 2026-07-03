"""Tests for migration 063 — add `warning_last_notified_at` cooldown column.

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


def _make_livelink_parameters(engine):
    is_pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY"
    with engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE TABLE livelink_parameters (id {pk}, "
                "param_key VARCHAR(100) UNIQUE NOT NULL, "
                "warning_min FLOAT, warning_max FLOAT)"
            )
        )


def test_063_adds_column(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_livelink_parameters(engine)

    _load("063_livelink_threshold_cooldown").upgrade(engine)

    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("livelink_parameters")}
    assert "warning_last_notified_at" in cols


def test_063_column_is_writable_and_nullable(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_livelink_parameters(engine)
    _load("063_livelink_threshold_cooldown").upgrade(engine)

    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO livelink_parameters (param_key, warning_max) VALUES ('0C-RPM', 100)")
        )
        row = conn.execute(
            text(
                "SELECT warning_last_notified_at FROM livelink_parameters WHERE param_key = '0C-RPM'"
            )
        ).fetchone()
    assert row is not None
    assert row[0] is None

    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE livelink_parameters SET warning_last_notified_at = "
                "CURRENT_TIMESTAMP WHERE param_key = '0C-RPM'"
            )
        )
        row = conn.execute(
            text(
                "SELECT warning_last_notified_at FROM livelink_parameters WHERE param_key = '0C-RPM'"
            )
        ).fetchone()
    assert row is not None
    assert row[0] is not None


def test_063_idempotent(engine_for_migration):
    """Second run is a no-op — no raise, no duplicate column."""
    _dialect, engine, _url = engine_for_migration
    _make_livelink_parameters(engine)
    mod = _load("063_livelink_threshold_cooldown")

    mod.upgrade(engine)
    mod.upgrade(engine)  # must not raise

    insp = inspect(engine)
    cols = [c["name"] for c in insp.get_columns("livelink_parameters")]
    assert cols.count("warning_last_notified_at") == 1


def test_063_missing_table_skips(engine_for_migration):
    """Fresh DB without livelink_parameters → migration must skip, not raise."""
    _dialect, engine, _url = engine_for_migration
    _load("063_livelink_threshold_cooldown").upgrade(engine)  # no table created

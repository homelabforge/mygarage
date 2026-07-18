"""Tests for migration 068 — drop orphaned backup tables.

Mirrors migration 060's fail-safe: empty orphaned ``*_backup`` tables are
dropped; a populated one is preserved for manual review. Runs on SQLite and
PostgreSQL via ``engine_for_migration``.
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


MIGRATION = "068_drop_orphan_backup_tables"

ORPHANS = (
    "service_records_backup_20251229",
    "collision_records_backup",
    "upgrade_records_backup",
)


def _create_orphans(engine) -> None:
    with engine.begin() as conn:
        for t in ORPHANS:
            conn.execute(text(f'CREATE TABLE "{t}" (id INTEGER PRIMARY KEY, note VARCHAR)'))


def test_drops_empty_orphan_backups(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _create_orphans(engine)

    _load(MIGRATION).upgrade(engine=engine)

    remaining = set(inspect(engine).get_table_names())
    for t in ORPHANS:
        assert t not in remaining, f"{t} should have been dropped"


def test_populated_backup_is_preserved(engine_for_migration):
    """Fail-safe: a backup with rows is kept for manual review."""
    _dialect, engine, _url = engine_for_migration
    _create_orphans(engine)
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO \"service_records_backup_20251229\" (id, note) VALUES (1, 'keep')")
        )

    _load(MIGRATION).upgrade(engine=engine)

    remaining = set(inspect(engine).get_table_names())
    assert "service_records_backup_20251229" in remaining, "populated backup must NOT be dropped"
    assert "collision_records_backup" not in remaining, "empty backups still get dropped"
    assert "upgrade_records_backup" not in remaining


def test_idempotent_across_absent_and_repeat(engine_for_migration):
    """Fresh install (never had the tables) and a second run are both no-ops."""
    _dialect, engine, _url = engine_for_migration
    migration = _load(MIGRATION)

    migration.upgrade(engine=engine)  # nothing present → no-op
    _create_orphans(engine)
    migration.upgrade(engine=engine)  # drops them
    migration.upgrade(engine=engine)  # must not raise

    remaining = set(inspect(engine).get_table_names())
    for t in ORPHANS:
        assert t not in remaining


def test_operational_error_is_swallowed(engine_for_migration, monkeypatch):
    """A per-table failure — INCLUDING a reflection error — must NOT escape
    upgrade().

    If it did, the runner would halt the pending-migration chain and — because
    this migration is NON-FATAL — the app would boot against a schema missing
    every later migration. Force ``has_table`` itself to raise (a reflection /
    connection failure, which the fix must catch by keeping reflection inside the
    per-table try/except); upgrade() must log and return normally.
    """
    _dialect, engine, _url = engine_for_migration
    migration = _load(MIGRATION)

    class _RaisingInspector:
        def has_table(self, _name):
            raise RuntimeError("simulated reflection failure")

    monkeypatch.setattr(migration, "inspect", lambda _engine: _RaisingInspector())

    migration.upgrade(engine=engine)  # must NOT raise despite has_table() failing

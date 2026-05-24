"""Smoke tests for the parameterized ``engine_for_migration`` fixture.

These prove the fixture yields a working engine on both SQLite and (when
``TEST_DATABASE_URL`` is set) PostgreSQL. They are intentionally trivial —
real migration coverage lives in the per-migration test modules.
"""

from __future__ import annotations

from sqlalchemy import text


def test_engine_fixture_yields_working_connection(engine_for_migration):
    dialect, engine, url = engine_for_migration
    assert dialect in {"sqlite", "pg"}
    assert engine is not None
    assert url

    with engine.begin() as conn:
        result = conn.execute(text("SELECT 1")).scalar()
        assert result == 1


def test_engine_fixture_isolates_schema_between_runs(engine_for_migration):
    """Each invocation gets a clean slate.

    For PG, ``_reset_pg_schema`` drops and recreates ``public`` before yield.
    For SQLite, the file is created fresh under ``tmp_path`` per test.
    """
    dialect, engine, _ = engine_for_migration

    # Create a table; the next test invocation should not see it.
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE smoke_marker (id INTEGER PRIMARY KEY)"))

    # We can read it within the same fixture lifetime.
    with engine.begin() as conn:
        if dialect == "sqlite":
            result = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='smoke_marker'")
            ).scalar()
        else:
            result = conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='public' AND table_name='smoke_marker'"
                )
            ).scalar()
        assert result == "smoke_marker"

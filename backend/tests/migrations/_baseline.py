"""Helpers for loading pre-migration PG baseline dumps.

Why this exists
---------------
Migration tests for new migrations need to run against a database that
represents the schema state *before* the migration is applied — i.e. the
state an existing user with the previous release has. The repository's
existing PG migration tests run ``Base.metadata.create_all()`` first,
which materializes the *current* model schema; by the time the migration
under test runs, every column/constraint it tries to add already exists
and the idempotency guard short-circuits the actual SQL.

That gap is what let migration 054 ship with two PG bugs (``DATETIME``
column type and ``ADD CONSTRAINT IF NOT EXISTS``). Neither piece of SQL
ever ran against PG in CI because ``create_all`` had already created the
column and the constraint.

A baseline dump is a pre-generated PG schema-only ``pg_dump`` of the
post-(N-1) state. Tests for migration N load it into a clean PG schema,
run migration N, and assert the expected post-state. Migration N's
literal SQL strings are guaranteed to execute — that's the whole point.

Generating new baselines
------------------------
See ``baselines/README.md`` for the procedure. In short: check out the
last-stable git tag in a worktree, run ``create_all`` + ``MigrationRunner``
through migrations 001..(N-1) against a clean PG instance, and
``pg_dump --schema-only --inserts``. The resulting file is committed.

Tests are SQLite-skipped: baselines are PG-specific by definition.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

BASELINE_DIR = Path(__file__).parent / "baselines"


def load_baseline(engine: Engine, name: str) -> None:
    """Load a baseline SQL dump into the given PG engine.

    Args:
        engine: A SQLAlchemy engine pointing at PostgreSQL. The engine's
            ``public`` schema is expected to be empty (use the
            ``engine_for_migration`` fixture, which resets it per test).
        name: Baseline name without the ``.sql`` extension, e.g.
            ``"pre_054"``.

    Raises:
        FileNotFoundError: If no baseline exists with that name.
        pytest.skip: If the engine is not PostgreSQL — baselines are
            inherently PG-specific (the dumps contain PG types,
            ``CREATE SEQUENCE``, etc.).
    """
    if engine.dialect.name != "postgresql":
        pytest.skip(f"Baseline {name!r} requires PostgreSQL (got {engine.dialect.name!r})")

    sql_path = BASELINE_DIR / f"{name}.sql"
    if not sql_path.exists():
        raise FileNotFoundError(
            f"Baseline {name!r} not found at {sql_path}. "
            f"See {BASELINE_DIR / 'README.md'} for regeneration steps."
        )

    sql = sql_path.read_text()

    with engine.begin() as conn:
        # SQLAlchemy's ``execute(text(sql))`` parses the entire script as
        # one statement. pg_dump output contains many; psycopg2 supports
        # multi-statement strings via the underlying connection's
        # ``cursor.execute``, which we reach through ``exec_driver_sql``.
        conn.exec_driver_sql(sql)


def baseline_exists(name: str) -> bool:
    """Return True if a baseline with the given name is committed."""
    return (BASELINE_DIR / f"{name}.sql").exists()

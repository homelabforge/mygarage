"""Tests for migration runner behavior: tracking, order, stop-on-failure, noop."""

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.migrations.runner import MigrationRunner, run_migrations


@pytest.mark.migrations
def test_tracking_table_created(migration_db):
    """Runner creates schema_migrations table on first run against a bare DB."""
    db_file, sync_url = migration_db
    runner = MigrationRunner(sync_url, Path("/nonexistent"))  # dir not needed for this test
    runner._ensure_migration_tracking_table()

    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    )
    assert cursor.fetchone() is not None, "schema_migrations table was not created"
    conn.close()


@pytest.mark.migrations
def test_discovery_order(migrations_dir):
    """Migration files are discovered in strictly ascending numeric order with no duplicates."""
    runner = MigrationRunner("sqlite:///:memory:", migrations_dir)
    discovered = runner._discover_migrations()
    names = [name for name, _ in discovered]

    assert len(names) > 0, "No migrations discovered"
    assert names == sorted(names), "Migrations not in ascending order"
    assert names[0].startswith("001_"), f"First migration should start with 001_, got {names[0]}"
    assert len(names) == len(set(names)), "Duplicate migration names found"


@pytest.mark.migrations
def test_runner_stops_on_failure(fake_migrations_failing_dir):
    """Runner stops at the first failure and does not mark subsequent migrations as applied."""
    fake_dir, db_file, sync_url = fake_migrations_failing_dir

    with pytest.raises(RuntimeError, match="forced failure"):
        run_migrations(sync_url, fake_dir)

    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("SELECT migration_name FROM schema_migrations ORDER BY id")
    applied = [row[0] for row in cursor.fetchall()]
    conn.close()

    assert "001_create_foo" in applied
    assert "002_create_bar" in applied
    assert "003_fail" not in applied


@pytest.mark.migrations
def test_second_run_is_noop(fake_migrations_success_dir):
    """Running migrations a second time against an already-migrated DB applies nothing new."""
    fake_dir, _, sync_url = fake_migrations_success_dir

    run_migrations(sync_url, fake_dir)

    engine = create_engine(sync_url)
    with engine.connect() as conn:
        count_after_first = conn.execute(
            text("SELECT COUNT(*) FROM schema_migrations")
        ).scalar()

    run_migrations(sync_url, fake_dir)

    with engine.connect() as conn:
        count_after_second = conn.execute(
            text("SELECT COUNT(*) FROM schema_migrations")
        ).scalar()

    engine.dispose()
    assert count_after_first == count_after_second, (
        f"Second run applied migrations: count went from {count_after_first} to {count_after_second}"
    )

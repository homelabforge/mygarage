"""Fixtures for migration behavior and crash recovery tests."""

from pathlib import Path

import pytest


@pytest.fixture
def migrations_dir() -> Path:
    """Path to the real migrations directory."""
    return Path(__file__).parent.parent.parent / "app" / "migrations"


@pytest.fixture
def migration_db(tmp_path, monkeypatch):
    """
    Bare isolated SQLite DB with both env vars pointing to the same file.

    Filename must be 'mygarage.db' so both migration styles resolve correctly:
      - sqlite3 migrations read DATABASE_PATH (= tmp_path/mygarage.db)
      - SQLAlchemy migrations read DATA_DIR and append 'mygarage.db' (= tmp_path/mygarage.db)
    """
    db_file = tmp_path / "mygarage.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_file))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return db_file, f"sqlite:///{db_file}"


def _write_fake_migration(path: Path, table_name: str) -> None:
    """Write a minimal synthetic migration that creates a table."""
    path.write_text(
        "import os, sqlite3\n"
        "def upgrade():\n"
        '    conn = sqlite3.connect(os.environ["DATABASE_PATH"])\n'
        f'    conn.execute("CREATE TABLE IF NOT EXISTS {table_name} (id INTEGER PRIMARY KEY)")\n'
        "    conn.commit(); conn.close()\n"
    )


@pytest.fixture
def fake_migrations_success_dir(tmp_path, monkeypatch):
    """Synthetic dir with 2 successful migrations. Used for noop and tracking tests."""
    fake_dir = tmp_path / "fake_migrations_success"
    fake_dir.mkdir()
    (fake_dir / "__init__.py").write_text("")
    db_file = tmp_path / "fake_success.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_file))
    _write_fake_migration(fake_dir / "001_create_foo.py", "foo")
    _write_fake_migration(fake_dir / "002_create_bar.py", "bar")
    return fake_dir, db_file, f"sqlite:///{db_file}"


@pytest.fixture
def fake_migrations_failing_dir(tmp_path, monkeypatch):
    """Synthetic dir with 2 good migrations then 1 that raises. Used for stop-on-failure test."""
    fake_dir = tmp_path / "fake_migrations_failing"
    fake_dir.mkdir()
    (fake_dir / "__init__.py").write_text("")
    db_file = tmp_path / "fake_failing.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_file))
    _write_fake_migration(fake_dir / "001_create_foo.py", "foo")
    _write_fake_migration(fake_dir / "002_create_bar.py", "bar")
    (fake_dir / "003_fail.py").write_text(
        "def upgrade():\n"
        '    raise RuntimeError("forced failure for testing")\n'
    )
    return fake_dir, db_file, f"sqlite:///{db_file}"

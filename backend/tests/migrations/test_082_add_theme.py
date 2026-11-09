"""Correctness + idempotency tests for migration 082_add_theme.

Covers:
- The nullable ``theme`` column is added to an existing users table.
- Existing rows get NULL (unset), not a defaulted value.
- Re-running the migration is a no-op (idempotent).
- Absent users table is a safe no-op.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import types
from pathlib import Path


def _load_migration() -> types.ModuleType:
    path = Path(__file__).parent.parent.parent / "app" / "migrations" / "082_add_theme.py"
    spec = importlib.util.spec_from_file_location("m082", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _setup_db(db_file: Path) -> None:
    """Users table WITHOUT the theme column, one pre-existing row."""
    conn = sqlite3.connect(str(db_file))
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username VARCHAR(50) NOT NULL
        );
        INSERT INTO users (username) VALUES ('existing');
        """
    )
    conn.commit()
    conn.close()


def _columns(db_file: Path) -> set[str]:
    conn = sqlite3.connect(str(db_file))
    cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    conn.close()
    return cols


def _themes(db_file: Path) -> dict[str, str | None]:
    conn = sqlite3.connect(str(db_file))
    rows = dict(conn.execute("SELECT username, theme FROM users"))
    conn.close()
    return rows


def test_adds_nullable_theme_column(tmp_path: Path, sync_engine) -> None:
    db_file = tmp_path / "m082.db"
    _setup_db(db_file)
    engine = sync_engine(f"sqlite:///{db_file}")

    m = _load_migration()
    m.upgrade(engine)

    assert "theme" in _columns(db_file), "theme column should be added"
    assert _themes(db_file)["existing"] is None, "existing rows must be NULL (unset), not defaulted"


def test_idempotent_rerun(tmp_path: Path, sync_engine) -> None:
    db_file = tmp_path / "m082.db"
    _setup_db(db_file)
    engine = sync_engine(f"sqlite:///{db_file}")

    m = _load_migration()
    m.upgrade(engine)
    m.upgrade(engine)  # second run must not raise

    assert "theme" in _columns(db_file)
    assert _themes(db_file)["existing"] is None


def test_absent_users_table_is_noop(tmp_path: Path, sync_engine) -> None:
    db_file = tmp_path / "m082-empty.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    engine = sync_engine(f"sqlite:///{db_file}")

    m = _load_migration()
    m.upgrade(engine)  # must not raise with no users table

"""Correctness + idempotency tests for migration 081_accent_color_nullable.

Covers:
- Existing accent_color='blue' (the 078 default) is reset to NULL.
- An explicitly-chosen non-'blue' accent (e.g. 'amber') is preserved.
- Re-running the migration is a no-op (idempotent).
- Absent users table / absent column is a safe no-op.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import types
from pathlib import Path

from sqlalchemy import create_engine


def _load_migration() -> types.ModuleType:
    path = (
        Path(__file__).parent.parent.parent / "app" / "migrations" / "081_accent_color_nullable.py"
    )
    spec = importlib.util.spec_from_file_location("m081", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _setup_db(db_file: Path) -> None:
    """Users table as migration 078 leaves it: accent_color VARCHAR DEFAULT 'blue'."""
    conn = sqlite3.connect(str(db_file))
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username VARCHAR(50) NOT NULL
        );
        ALTER TABLE users ADD COLUMN accent_color VARCHAR(20) DEFAULT 'blue';
        INSERT INTO users (username, accent_color) VALUES ('defaulted', 'blue');
        INSERT INTO users (username, accent_color) VALUES ('chose-amber', 'amber');
        """
    )
    conn.commit()
    conn.close()


def _accents(db_file: Path) -> dict[str, str | None]:
    conn = sqlite3.connect(str(db_file))
    rows = dict(conn.execute("SELECT username, accent_color FROM users"))
    conn.close()
    return rows


def test_resets_defaulted_blue_preserves_explicit(tmp_path: Path) -> None:
    db_file = tmp_path / "m081.db"
    _setup_db(db_file)
    engine = create_engine(f"sqlite:///{db_file}")

    m = _load_migration()
    m.upgrade(engine)

    accents = _accents(db_file)
    assert accents["defaulted"] is None, "defaulted 'blue' should become NULL (unset)"
    assert accents["chose-amber"] == "amber", "an explicit non-blue pick must be preserved"


def test_idempotent_rerun(tmp_path: Path) -> None:
    db_file = tmp_path / "m081.db"
    _setup_db(db_file)
    engine = create_engine(f"sqlite:///{db_file}")

    m = _load_migration()
    m.upgrade(engine)
    m.upgrade(engine)  # second run must not raise

    accents = _accents(db_file)
    assert accents["defaulted"] is None
    assert accents["chose-amber"] == "amber"


def test_absent_users_table_is_noop(tmp_path: Path) -> None:
    db_file = tmp_path / "m081-empty.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    engine = create_engine(f"sqlite:///{db_file}")

    m = _load_migration()
    m.upgrade(engine)  # must not raise with no users table

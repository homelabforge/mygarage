"""Migration 156: users.date_format, day-first or month-first dates. Every
existing user gets 'mdy', the order English dates have always used."""

from __future__ import annotations

import importlib.util
import sqlite3
import types
from pathlib import Path

from sqlalchemy import create_engine


def _load() -> types.ModuleType:
    path = Path(__file__).parent.parent.parent / "app" / "migrations" / "156_add_date_format.py"
    spec = importlib.util.spec_from_file_location("m156", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _setup(db_file: Path) -> None:
    conn = sqlite3.connect(str(db_file))
    conn.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(50) NOT NULL);
        INSERT INTO users (id, username) VALUES (1, 'existing');
        """
    )
    conn.commit()
    conn.close()


def test_adds_a_not_null_column_and_existing_users_keep_month_first(tmp_path: Path) -> None:
    db_file = tmp_path / "m156.db"
    _setup(db_file)
    _load().upgrade(create_engine(f"sqlite:///{db_file}"))

    conn = sqlite3.connect(str(db_file))
    cols = {r[1]: r for r in conn.execute("PRAGMA table_info(users)")}
    assert "date_format" in cols
    assert cols["date_format"][2].upper() == "VARCHAR(10)"
    assert cols["date_format"][3] == 1  # NOT NULL
    assert conn.execute("SELECT date_format FROM users WHERE id = 1").fetchone()[0] == "mdy"
    # A row inserted without the column still gets the default.
    conn.execute("INSERT INTO users (id, username) VALUES (2, 'later')")
    assert conn.execute("SELECT date_format FROM users WHERE id = 2").fetchone()[0] == "mdy"
    conn.close()


def test_is_idempotent(tmp_path: Path) -> None:
    db_file = tmp_path / "m156.db"
    _setup(db_file)
    engine = create_engine(f"sqlite:///{db_file}")
    module = _load()
    module.upgrade(engine)
    module.upgrade(engine)  # must not raise "duplicate column"


def test_is_fatal() -> None:
    assert _load().FATAL is True

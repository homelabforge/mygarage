"""Migration 120: users.dashboard_sort, the order the dashboard opens in. Every
existing user gets 'name', the order the dashboard has always opened in."""

from __future__ import annotations

import importlib.util
import sqlite3
import types
from pathlib import Path


def _load() -> types.ModuleType:
    path = Path(__file__).parent.parent.parent / "app" / "migrations" / "120_add_dashboard_sort.py"
    spec = importlib.util.spec_from_file_location("m120", path)
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


def test_adds_a_not_null_column_and_existing_users_open_on_name(
    tmp_path: Path, sync_engine
) -> None:
    db_file = tmp_path / "m120.db"
    _setup(db_file)
    _load().upgrade(sync_engine(f"sqlite:///{db_file}"))

    conn = sqlite3.connect(str(db_file))
    cols = {r[1]: r for r in conn.execute("PRAGMA table_info(users)")}
    assert "dashboard_sort" in cols
    assert cols["dashboard_sort"][2].upper() == "VARCHAR(16)"
    assert cols["dashboard_sort"][3] == 1  # NOT NULL
    assert conn.execute("SELECT dashboard_sort FROM users WHERE id = 1").fetchone()[0] == "name"
    # A row inserted without the column still gets the default.
    conn.execute("INSERT INTO users (id, username) VALUES (2, 'later')")
    assert conn.execute("SELECT dashboard_sort FROM users WHERE id = 2").fetchone()[0] == "name"
    conn.close()


def test_is_idempotent(tmp_path: Path, sync_engine) -> None:
    db_file = tmp_path / "m120.db"
    _setup(db_file)
    engine = sync_engine(f"sqlite:///{db_file}")
    module = _load()
    module.upgrade(engine)
    module.upgrade(engine)  # must not raise "duplicate column"


def test_is_fatal() -> None:
    assert _load().FATAL is True

"""Migration 010 only reports on password hashes; its all-Argon2 report has no stale advice."""

from __future__ import annotations

import importlib.util
import sqlite3
import types
from pathlib import Path

import pytest
from sqlalchemy import create_engine

_ARGON2 = "$argon2id$v=19$m=102400,t=2,p=8$c2FsdA$aGFzaA"


def _load_migration() -> types.ModuleType:
    path = Path(__file__).parent.parent.parent / "app" / "migrations" / "010_migrate_to_argon2.py"
    spec = importlib.util.spec_from_file_location("m010", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _setup_db(db_file: Path, hashes: list[str]) -> None:
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, hashed_password VARCHAR(255) NOT NULL)"
    )
    conn.executemany("INSERT INTO users (hashed_password) VALUES (?)", [(h,) for h in hashes])
    conn.commit()
    conn.close()


def test_an_all_argon2_report_doesnt_mention_bcrypt_in_pyproject(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """bcrypt was never a dependency, so telling you to drop it from pyproject is wrong."""
    db_file = tmp_path / "m010.db"
    _setup_db(db_file, [_ARGON2, _ARGON2])

    engine = create_engine(f"sqlite:///{db_file}")
    try:
        _load_migration().upgrade(engine)
    finally:
        engine.dispose()

    out = capsys.readouterr().out
    assert "All passwords migrated to Argon2" in out
    assert "pyproject" not in out
    assert "You can remove 'bcrypt'" not in out

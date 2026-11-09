"""Migration 119: nullable vehicles.distance_unit (#172). No backfill: NULL is
"Account default", so every existing vehicle behaves exactly as before."""

from __future__ import annotations

import importlib.util
import sqlite3
import types
from pathlib import Path


def _load() -> types.ModuleType:
    path = (
        Path(__file__).parent.parent.parent
        / "app"
        / "migrations"
        / "119_add_vehicle_distance_unit.py"
    )
    spec = importlib.util.spec_from_file_location("m119", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _setup(db_file: Path) -> None:
    conn = sqlite3.connect(str(db_file))
    conn.executescript(
        """
        CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY, nickname VARCHAR(100) NOT NULL);
        INSERT INTO vehicles (vin, nickname) VALUES ('M119VIN0000000001', 'Existing');
        """
    )
    conn.commit()
    conn.close()


def test_adds_a_nullable_column_and_leaves_rows_null(tmp_path: Path, sync_engine) -> None:
    db_file = tmp_path / "m119.db"
    _setup(db_file)
    _load().upgrade(sync_engine(f"sqlite:///{db_file}"))

    conn = sqlite3.connect(str(db_file))
    cols = {r[1]: r for r in conn.execute("PRAGMA table_info(vehicles)")}
    assert "distance_unit" in cols
    assert cols["distance_unit"][2].upper() == "VARCHAR(2)"
    assert cols["distance_unit"][3] == 0  # nullable
    assert conn.execute("SELECT distance_unit FROM vehicles").fetchone()[0] is None
    conn.close()


def test_is_idempotent(tmp_path: Path, sync_engine) -> None:
    db_file = tmp_path / "m119.db"
    _setup(db_file)
    engine = sync_engine(f"sqlite:///{db_file}")
    module = _load()
    module.upgrade(engine)
    module.upgrade(engine)  # must not raise "duplicate column"


def test_is_fatal() -> None:
    assert _load().FATAL is True

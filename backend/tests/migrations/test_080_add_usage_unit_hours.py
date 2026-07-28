"""Correctness + idempotency tests for migration 080_add_usage_unit_hours.

Covers:
- usage_unit + current_hours columns get added.
- Existing rows are backfilled to usage_unit='distance' (non-null).
- current_hours is nullable.
- Re-running the migration is a no-op (idempotent).
"""

from __future__ import annotations

import importlib.util
import sqlite3
import types
from pathlib import Path

from sqlalchemy import create_engine


def _load_migration() -> types.ModuleType:
    path = (
        Path(__file__).parent.parent.parent / "app" / "migrations" / "080_add_usage_unit_hours.py"
    )
    spec = importlib.util.spec_from_file_location("m080", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _setup_db(db_file: Path) -> None:
    conn = sqlite3.connect(str(db_file))
    conn.executescript(
        """
        CREATE TABLE vehicles (
            vin VARCHAR(17) PRIMARY KEY,
            nickname VARCHAR(100) NOT NULL,
            vehicle_type VARCHAR(20) NOT NULL
        );
        INSERT INTO vehicles (vin, nickname, vehicle_type)
            VALUES ('CARVIN00000000001', 'DailyDriver', 'Car');
        """
    )
    conn.commit()
    conn.close()


def _columns(db_file: Path) -> dict[str, dict]:
    conn = sqlite3.connect(str(db_file))
    cols = {
        r[1]: {"notnull": r[3], "dflt": r[4]} for r in conn.execute("PRAGMA table_info(vehicles)")
    }
    conn.close()
    return cols


def test_adds_columns_and_backfills(tmp_path: Path) -> None:
    db_file = tmp_path / "m080.db"
    _setup_db(db_file)
    m = _load_migration()
    engine = create_engine(f"sqlite:///{db_file}")

    m.upgrade(engine)

    cols = _columns(db_file)
    assert "usage_unit" in cols
    assert "current_hours" in cols

    conn = sqlite3.connect(str(db_file))
    # Existing row backfilled to 'distance' (never NULL).
    assert (
        conn.execute("SELECT usage_unit FROM vehicles WHERE vin='CARVIN00000000001'").fetchone()[0]
        == "distance"
    )
    # current_hours is nullable and starts NULL.
    assert (
        conn.execute("SELECT current_hours FROM vehicles WHERE vin='CARVIN00000000001'").fetchone()[
            0
        ]
        is None
    )
    # A vehicle can be stored with hours.
    conn.execute(
        "INSERT INTO vehicles (vin, nickname, vehicle_type, usage_unit, current_hours) "
        "VALUES ('ATVVIN00000000001', 'Quad', 'ATV', 'hours', 42.5)"
    )
    conn.commit()
    assert (
        conn.execute("SELECT current_hours FROM vehicles WHERE vin='ATVVIN00000000001'").fetchone()[
            0
        ]
        == 42.5
    )
    conn.close()


def test_idempotent_rerun(tmp_path: Path) -> None:
    db_file = tmp_path / "m080_idem.db"
    _setup_db(db_file)
    m = _load_migration()
    engine = create_engine(f"sqlite:///{db_file}")

    m.upgrade(engine)
    m.upgrade(engine)  # must not raise or double-add

    cols = _columns(db_file)
    assert "usage_unit" in cols and "current_hours" in cols

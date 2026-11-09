"""Migration 144: fuel_records.fuel_grade, the EN 16942 pump label (#211).

Nullable VARCHAR(10), no backfill, no CHECK (the vocabulary is validated by
Pydantic, like octane / diesel_grade from migration 105). FATAL, because the
model declares the column. Parameterised over SQLite and PostgreSQL via
`engine_for_migration`.
"""

import importlib.util
import sqlite3
from pathlib import Path

from sqlalchemy import inspect, text

import app.migrations as _m

_NAME = "144_add_fuel_grade"


def _load(name: str = _NAME):
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_fuel_records(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE fuel_records (id INTEGER PRIMARY KEY, vin VARCHAR(17) NOT NULL, "
                "date DATE NOT NULL, octane INTEGER, diesel_grade VARCHAR(10))"
            )
        )
        conn.execute(
            text(
                "INSERT INTO fuel_records (id, vin, date, octane) "
                "VALUES (1, '1HGCM82633A123456', '2026-05-01', 95)"
            )
        )


def test_144_adds_a_nullable_varchar10(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_fuel_records(engine)
    _load().upgrade(engine)
    cols = {c["name"]: c for c in inspect(engine).get_columns("fuel_records")}
    assert "fuel_grade" in cols
    assert cols["fuel_grade"]["nullable"] is True
    with engine.connect() as conn:
        # No backfill: the label of a past fill-up is unknown, so it stays NULL.
        assert (
            conn.execute(text("SELECT fuel_grade FROM fuel_records WHERE id = 1")).scalar() is None
        )
        assert conn.execute(text("SELECT octane FROM fuel_records WHERE id = 1")).scalar() == 95


def test_144_is_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_fuel_records(engine)
    mod = _load()
    mod.upgrade(engine)
    mod.upgrade(engine)
    assert [c["name"] for c in inspect(engine).get_columns("fuel_records")].count("fuel_grade") == 1


def test_144_missing_fuel_records_table_skips(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _load().upgrade(engine)
    assert not inspect(engine).has_table("fuel_records")


def test_144_is_fatal():
    assert _load().FATAL is True


def test_144_sqlite_declares_varchar10_nullable(tmp_path: Path, sync_engine) -> None:
    db_file = tmp_path / "m144.db"
    engine = sync_engine(f"sqlite:///{db_file}")
    _make_fuel_records(engine)
    _load().upgrade(engine)

    conn = sqlite3.connect(str(db_file))
    cols = {r[1]: r for r in conn.execute("PRAGMA table_info(fuel_records)")}
    conn.close()
    assert cols["fuel_grade"][2].upper() == "VARCHAR(10)"
    assert cols["fuel_grade"][3] == 0  # nullable

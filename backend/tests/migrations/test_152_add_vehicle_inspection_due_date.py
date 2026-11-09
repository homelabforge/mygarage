"""Migration 152: vehicles.inspection_due_date, field X.1's deadline (#211).

A nullable DATE, no backfill. FATAL, because the model declares the column.
Parameterised over SQLite and PostgreSQL via `engine_for_migration`.
"""

import importlib.util
import sqlite3
from datetime import date
from pathlib import Path

from sqlalchemy import inspect, text

import app.migrations as _m

_NAME = "152_add_vehicle_inspection_due_date"


def _load(name: str = _NAME):
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_vehicles(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY, nickname VARCHAR(100), "
                "first_registration_date DATE)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO vehicles (vin, nickname, first_registration_date) "
                "VALUES ('1HGCM82633A004352', 'Clio', '2019-04-12')"
            )
        )


def test_152_adds_a_nullable_date_without_backfill(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_vehicles(engine)
    _load().upgrade(engine)
    cols = {c["name"]: c for c in inspect(engine).get_columns("vehicles")}
    assert "inspection_due_date" in cols
    assert cols["inspection_due_date"]["nullable"] is True
    with engine.begin() as conn:
        assert conn.execute(text("SELECT inspection_due_date FROM vehicles")).scalar() is None
        conn.execute(text("UPDATE vehicles SET inspection_due_date = '2026-02-10'"))
        stored = conn.execute(text("SELECT inspection_due_date FROM vehicles")).scalar()
    assert str(stored) == date(2026, 2, 10).isoformat()


def test_152_is_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_vehicles(engine)
    mod = _load()
    mod.upgrade(engine)
    mod.upgrade(engine)
    names = [c["name"] for c in inspect(engine).get_columns("vehicles")]
    assert names.count("inspection_due_date") == 1


def test_152_missing_table_skips(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _load().upgrade(engine)
    assert not inspect(engine).has_table("vehicles")


def test_152_is_fatal():
    assert _load().FATAL is True


def test_152_sqlite_declares_a_nullable_date(tmp_path: Path, sync_engine) -> None:
    db_file = tmp_path / "m152.db"
    engine = sync_engine(f"sqlite:///{db_file}")
    _make_vehicles(engine)
    _load().upgrade(engine)
    conn = sqlite3.connect(str(db_file))
    cols = {r[1]: r for r in conn.execute("PRAGMA table_info(vehicles)")}
    conn.close()
    assert cols["inspection_due_date"][2].upper() == "DATE"
    assert cols["inspection_due_date"][3] == 0

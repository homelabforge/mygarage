"""Migration 153: vehicles.wheel_layout, the per-vehicle layout override (#272).

A nullable VARCHAR(20), no backfill: NULL means "whatever the type usually
has". FATAL, because the model declares the column. Parameterised over SQLite
and PostgreSQL via `engine_for_migration`.
"""

import importlib.util
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

import app.migrations as _m

_NAME = "153_add_vehicle_wheel_layout"


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
                "vehicle_type VARCHAR(20))"
            )
        )
        conn.execute(
            text(
                "INSERT INTO vehicles (vin, nickname, vehicle_type) "
                "VALUES ('1HGCM82633A004352', 'Bonneville', 'Motorcycle')"
            )
        )


def test_153_adds_a_nullable_column_without_backfill(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_vehicles(engine)
    _load().upgrade(engine)
    cols = {c["name"]: c for c in inspect(engine).get_columns("vehicles")}
    assert "wheel_layout" in cols
    assert cols["wheel_layout"]["nullable"] is True
    with engine.begin() as conn:
        # A Motorcycle stays NULL: the type default does the work, not a backfill.
        assert conn.execute(text("SELECT wheel_layout FROM vehicles")).scalar() is None
        conn.execute(text("UPDATE vehicles SET wheel_layout = 'trike_2f1r'"))
        stored = conn.execute(text("SELECT wheel_layout FROM vehicles")).scalar()
    assert stored == "trike_2f1r"


def test_153_is_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_vehicles(engine)
    mod = _load()
    mod.upgrade(engine)
    mod.upgrade(engine)
    names = [c["name"] for c in inspect(engine).get_columns("vehicles")]
    assert names.count("wheel_layout") == 1


def test_153_missing_table_skips(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _load().upgrade(engine)
    assert not inspect(engine).has_table("vehicles")


def test_153_is_fatal():
    assert _load().FATAL is True


def test_153_sqlite_declares_a_nullable_varchar20(tmp_path: Path) -> None:
    db_file = tmp_path / "m153.db"
    engine = create_engine(f"sqlite:///{db_file}")
    _make_vehicles(engine)
    _load().upgrade(engine)
    conn = sqlite3.connect(str(db_file))
    cols = {r[1]: r for r in conn.execute("PRAGMA table_info(vehicles)")}
    conn.close()
    assert cols["wheel_layout"][2].upper() == "VARCHAR(20)"
    assert cols["wheel_layout"][3] == 0

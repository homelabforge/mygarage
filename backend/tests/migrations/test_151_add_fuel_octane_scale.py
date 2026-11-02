"""Migration 151: fuel_records.octane_scale, the scale an octane was read on (B4).

Nullable VARCHAR(3) holding 'RON' or 'AKI', no backfill (a past fill-up's
scale is unknown and is never inferred from today's country settings), no
CHECK (validated by Pydantic like octane itself). FATAL, because the model
declares the column. Parameterised over SQLite and PostgreSQL via
`engine_for_migration`.
"""

import importlib.util
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

import app.migrations as _m

_NAME = "151_add_fuel_octane_scale"


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
                "date DATE NOT NULL, octane INTEGER, fuel_grade VARCHAR(10))"
            )
        )
        conn.execute(
            text(
                "INSERT INTO fuel_records (id, vin, date, octane) "
                "VALUES (1, '1HGCM82633A123456', '2026-05-01', 95)"
            )
        )


def test_151_adds_a_nullable_varchar3_without_backfill(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_fuel_records(engine)
    _load().upgrade(engine)
    cols = {c["name"]: c for c in inspect(engine).get_columns("fuel_records")}
    assert "octane_scale" in cols
    assert cols["octane_scale"]["nullable"] is True
    with engine.connect() as conn:
        row = conn.execute(text("SELECT octane, octane_scale FROM fuel_records WHERE id = 1")).one()
    assert tuple(row) == (95, None)


def test_151_stores_a_scale(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_fuel_records(engine)
    _load().upgrade(engine)
    with engine.begin() as conn:
        conn.execute(text("UPDATE fuel_records SET octane_scale = 'RON' WHERE id = 1"))
        assert conn.execute(text("SELECT octane_scale FROM fuel_records")).scalar() == "RON"


def test_151_is_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_fuel_records(engine)
    mod = _load()
    mod.upgrade(engine)
    mod.upgrade(engine)
    names = [c["name"] for c in inspect(engine).get_columns("fuel_records")]
    assert names.count("octane_scale") == 1


def test_151_missing_fuel_records_table_skips(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _load().upgrade(engine)
    assert not inspect(engine).has_table("fuel_records")


def test_151_is_fatal():
    assert _load().FATAL is True


def test_151_sqlite_declares_varchar3_nullable(tmp_path: Path) -> None:
    db_file = tmp_path / "m151.db"
    engine = create_engine(f"sqlite:///{db_file}")
    _make_fuel_records(engine)
    _load().upgrade(engine)

    conn = sqlite3.connect(str(db_file))
    cols = {r[1]: r for r in conn.execute("PRAGMA table_info(fuel_records)")}
    conn.close()
    assert cols["octane_scale"][2].upper() == "VARCHAR(3)"
    assert cols["octane_scale"][3] == 0  # nullable

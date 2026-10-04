"""Migration 124: supplies.volume_unit, the per-supply display unit token (#191).

Nullable VARCHAR(8), no backfill, no CHECK. FATAL, because the model declares the
column. Parameterised over SQLite and PostgreSQL via `engine_for_migration`.
"""

import importlib.util
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

import app.migrations as _m

_NAME = "124_supply_volume_unit"


def _load(name: str = _NAME):
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_supplies(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE supplies (id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL, "
                "unit_type VARCHAR(10) NOT NULL)"
            )
        )
        conn.execute(text("INSERT INTO supplies (id, name, unit_type) VALUES (1, 'Oil', 'volume')"))


def test_124_adds_a_nullable_varchar8(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_supplies(engine)
    _load().upgrade(engine)
    cols = {c["name"]: c for c in inspect(engine).get_columns("supplies")}
    assert "volume_unit" in cols
    assert cols["volume_unit"]["nullable"] is True
    with engine.connect() as conn:
        assert conn.execute(text("SELECT volume_unit FROM supplies WHERE id = 1")).scalar() is None


def test_124_is_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_supplies(engine)
    mod = _load()
    mod.upgrade(engine)
    mod.upgrade(engine)
    assert [c["name"] for c in inspect(engine).get_columns("supplies")].count("volume_unit") == 1


def test_124_missing_supplies_table_skips(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _load().upgrade(engine)
    assert not inspect(engine).has_table("supplies")


def test_124_is_fatal():
    assert _load().FATAL is True


def test_124_sqlite_declares_varchar8_nullable(tmp_path: Path) -> None:
    db_file = tmp_path / "m124.db"
    engine = create_engine(f"sqlite:///{db_file}")
    _make_supplies(engine)
    _load().upgrade(engine)

    conn = sqlite3.connect(str(db_file))
    cols = {r[1]: r for r in conn.execute("PRAGMA table_info(supplies)")}
    conn.close()
    assert cols["volume_unit"][2].upper() == "VARCHAR(8)"
    assert cols["volume_unit"][3] == 0  # nullable

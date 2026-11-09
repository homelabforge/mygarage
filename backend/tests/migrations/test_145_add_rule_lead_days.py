"""Migration 145: vehicle_maintenance_rules.lead_days (#211).

Nullable INTEGER, no backfill, no CHECK. FATAL, because the model declares
the column. Parameterised over SQLite and PostgreSQL via
`engine_for_migration`.
"""

import importlib.util
import sqlite3
from pathlib import Path

from sqlalchemy import inspect, text

import app.migrations as _m

_NAME = "145_add_rule_lead_days"


def _load(name: str = _NAME):
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_rules(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE vehicle_maintenance_rules (id INTEGER PRIMARY KEY, "
                "vin VARCHAR(17) NOT NULL, title VARCHAR(200) NOT NULL, "
                "interval_months INTEGER, source VARCHAR(20) NOT NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO vehicle_maintenance_rules (id, vin, title, interval_months, source) "
                "VALUES (1, '1HGCM82633A123456', 'Oil change', 6, 'manual')"
            )
        )


def test_145_adds_a_nullable_integer(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_rules(engine)
    _load().upgrade(engine)
    cols = {c["name"]: c for c in inspect(engine).get_columns("vehicle_maintenance_rules")}
    assert "lead_days" in cols
    assert cols["lead_days"]["nullable"] is True
    with engine.connect() as conn:
        # No backfill: no existing rule has a lead window.
        row = conn.execute(
            text("SELECT lead_days, interval_months FROM vehicle_maintenance_rules WHERE id = 1")
        ).one()
        assert row == (None, 6)


def test_145_is_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_rules(engine)
    mod = _load()
    mod.upgrade(engine)
    mod.upgrade(engine)
    names = [c["name"] for c in inspect(engine).get_columns("vehicle_maintenance_rules")]
    assert names.count("lead_days") == 1


def test_145_missing_table_skips(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _load().upgrade(engine)
    assert not inspect(engine).has_table("vehicle_maintenance_rules")


def test_145_is_fatal():
    assert _load().FATAL is True


def test_145_sqlite_declares_integer_nullable(tmp_path: Path, sync_engine) -> None:
    db_file = tmp_path / "m145.db"
    engine = sync_engine(f"sqlite:///{db_file}")
    _make_rules(engine)
    _load().upgrade(engine)

    conn = sqlite3.connect(str(db_file))
    cols = {r[1]: r for r in conn.execute("PRAGMA table_info(vehicle_maintenance_rules)")}
    conn.close()
    assert cols["lead_days"][2].upper() == "INTEGER"
    assert cols["lead_days"][3] == 0  # nullable

"""Migration 147: the EU registration-certificate fields on vehicles (#211).

Seven nullable columns, no backfill, no CHECK. FATAL, because the ORM
declares every column. Parameterised over SQLite and PostgreSQL via
`engine_for_migration`.
"""

import importlib.util
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

import app.migrations as _m

_NAME = "147_add_vehicle_eu_fields"
_COLUMNS = (
    "euro_emission_class",
    "fiscal_power",
    "co2_g_km",
    "power_kw",
    "eu_category",
    "national_category",
    "lez_class",
)


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
                "CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY, nickname VARCHAR(100) NOT NULL, "
                "first_registration_date DATE)"
            )
        )
        conn.execute(
            text("INSERT INTO vehicles (vin, nickname) VALUES ('VF1RFB00X56123456', 'Clio')")
        )


def test_147_adds_the_seven_nullable_columns(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_vehicles(engine)
    _load().upgrade(engine)
    cols = {c["name"]: c for c in inspect(engine).get_columns("vehicles")}
    for name in _COLUMNS:
        assert name in cols, name
        assert cols[name]["nullable"] is True, name
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT euro_emission_class, fiscal_power, co2_g_km, power_kw, eu_category, "
                "national_category, lez_class FROM vehicles"
            )
        ).one()
        assert row == (None,) * 7
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE vehicles SET euro_emission_class = 'Euro 6d-TEMP', fiscal_power = 5, "
                "co2_g_km = 118, power_kw = 74, eu_category = 'M1', national_category = 'VP', "
                "lez_class = '1'"
            )
        )
    with engine.connect() as conn:
        assert conn.execute(text("SELECT fiscal_power, eu_category FROM vehicles")).one() == (
            5,
            "M1",
        )


def test_147_is_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_vehicles(engine)
    mod = _load()
    mod.upgrade(engine)
    mod.upgrade(engine)
    names = [c["name"] for c in inspect(engine).get_columns("vehicles")]
    for name in _COLUMNS:
        assert names.count(name) == 1


def test_147_missing_table_skips(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _load().upgrade(engine)
    assert not inspect(engine).has_table("vehicles")


def test_147_is_fatal():
    assert _load().FATAL is True


def test_147_sqlite_declares_types(tmp_path: Path) -> None:
    db_file = tmp_path / "m147.db"
    engine = create_engine(f"sqlite:///{db_file}")
    _make_vehicles(engine)
    _load().upgrade(engine)
    conn = sqlite3.connect(str(db_file))
    cols = {r[1]: r for r in conn.execute("PRAGMA table_info(vehicles)")}
    conn.close()
    assert cols["euro_emission_class"][2].upper() == "VARCHAR(12)"
    assert cols["fiscal_power"][2].upper() == "INTEGER"
    assert cols["eu_category"][2].upper() == "VARCHAR(5)"
    assert cols["lez_class"][2].upper() == "VARCHAR(10)"
    assert all(cols[name][3] == 0 for name in _COLUMNS)  # nullable

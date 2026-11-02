"""Migration 150: vehicles.identifier_type and vehicles.identifier (#226).

identifier_type is NOT NULL DEFAULT 'vin', so every existing vehicle keeps
meaning "the key is the VIN". identifier is a nullable VARCHAR(64). FATAL,
because the model declares both. Parameterised over SQLite and PostgreSQL.
"""

import importlib.util
from pathlib import Path

from sqlalchemy import inspect, text

import app.migrations as _m

_NAME = "150_add_vehicle_identifier"


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
                "vehicle_type VARCHAR(20) NOT NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO vehicles (vin, nickname, vehicle_type) VALUES ('1HGCM82633A004352', 'Accord', 'Car')"
            )
        )


def test_150_adds_both_columns_and_existing_rows_read_as_vin(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_vehicles(engine)
    _load().upgrade(engine)
    cols = {c["name"]: c for c in inspect(engine).get_columns("vehicles")}
    assert cols["identifier_type"]["nullable"] is False
    assert cols["identifier"]["nullable"] is True
    with engine.connect() as conn:
        row = conn.execute(text("SELECT identifier_type, identifier FROM vehicles")).one()
    assert tuple(row) == ("vin", None)


def test_150_new_rows_default_to_vin(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_vehicles(engine)
    _load().upgrade(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO vehicles (vin, nickname, vehicle_type) VALUES ('QABCDEFGH12345678', 'Mower', 'Mower')"
            )
        )
        assert (
            conn.execute(
                text("SELECT identifier_type FROM vehicles WHERE vin = 'QABCDEFGH12345678'")
            ).scalar()
            == "vin"
        )


def test_150_is_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_vehicles(engine)
    mod = _load()
    mod.upgrade(engine)
    mod.upgrade(engine)
    names = [c["name"] for c in inspect(engine).get_columns("vehicles")]
    assert names.count("identifier_type") == 1
    assert names.count("identifier") == 1


def test_150_missing_vehicles_table_skips(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _load().upgrade(engine)


def test_150_is_fatal():
    assert _load().FATAL is True

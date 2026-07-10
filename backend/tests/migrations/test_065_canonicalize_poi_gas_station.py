"""Tests for migration 065 — canonicalize the split gas-station tag.

Historically the fuel-record save path wrote poi_category='fuel_station'
while the fuel-form quick-add wrote 'gas_station'. This FATAL migration
collapses legacy 'fuel_station' rows onto the canonical 'gas_station' value
so the Gas-Stations filter, autocomplete ranking, and vendor-sync exclusion
all match one string. Parameterized over SQLite + PostgreSQL.
"""

import importlib.util
from pathlib import Path

from sqlalchemy import text

import app.migrations as _m


def _load(name):
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_SEED_ROWS = [
    ("Legacy Server Station", "fuel_station"),  # -> gas_station
    ("Quick Add Station", "gas_station"),  # already canonical
    ("Joe's Auto", "auto_shop"),  # untouched
    ("No Category Contact", None),  # untouched
]


def _make_address_book(engine):
    is_pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY"
    with engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE TABLE address_book (id {pk}, "
                "business_name VARCHAR(150) NOT NULL, "
                "poi_category VARCHAR(50))"
            )
        )
        for name, poi in _SEED_ROWS:
            conn.execute(
                text("INSERT INTO address_book (business_name, poi_category) VALUES (:n, :p)"),
                {"n": name, "p": poi},
            )


def _fetch(engine):
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT business_name, poi_category FROM address_book ORDER BY business_name")
        ).fetchall()
    return {r[0]: r[1] for r in rows}


def test_065_is_marked_fatal():
    assert _load("065_canonicalize_poi_gas_station").FATAL is True


def test_065_rekeys_fuel_station_to_gas_station(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_address_book(engine)
    _load("065_canonicalize_poi_gas_station").upgrade(engine)
    rows = _fetch(engine)
    assert rows["Legacy Server Station"] == "gas_station"
    assert rows["Quick Add Station"] == "gas_station"
    assert rows["Joe's Auto"] == "auto_shop"
    assert rows["No Category Contact"] is None
    # No fuel_station rows survive.
    assert "fuel_station" not in set(rows.values())


def test_065_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_address_book(engine)
    mod = _load("065_canonicalize_poi_gas_station")
    mod.upgrade(engine)
    first = _fetch(engine)
    mod.upgrade(engine)
    assert _fetch(engine) == first


def test_065_missing_table_skips(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _load("065_canonicalize_poi_gas_station").upgrade(engine)  # no table → must not raise

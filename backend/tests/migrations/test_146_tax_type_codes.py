"""Migration 146: tax types become codes (#211).

Parameterised over SQLite and PostgreSQL via `engine_for_migration`: the
CHECK goes, the four legacy values are rewritten, null and unknown values
are left alone, the index and the foreign key survive, and a second run
changes nothing. The SQLite shapes of the CHECK are covered in
`tests/unit/utils/test_check_constraint.py`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError

import app.migrations as _m

_NAME = "146_tax_type_codes"


def _load(name: str = _NAME):
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_tables(engine: Engine, *, with_check: bool = True) -> None:
    check = (
        ", CONSTRAINT check_tax_type CHECK "
        "(tax_type IN ('Registration', 'Inspection', 'Property Tax', 'Tolls'))"
        if with_check
        else ""
    )
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY, nickname VARCHAR(100))")
        )
        conn.execute(
            text(
                "CREATE TABLE tax_records ("
                "id INTEGER PRIMARY KEY, "
                "vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE, "
                "date DATE NOT NULL, tax_type VARCHAR(30), amount NUMERIC(12, 2) NOT NULL, "
                f"renewal_date DATE, notes TEXT{check})"
            )
        )
        conn.execute(text("CREATE INDEX idx_tax_records_vin ON tax_records (vin)"))
        conn.execute(text("INSERT INTO vehicles (vin, nickname) VALUES ('CARVIN00000000001', 'A')"))
        rows = [
            (1, "Registration", 85.5),
            (2, "Inspection", 40.0),
            (3, "Property Tax", 150.0),
            (4, "Tolls", 12.25),
            (5, None, 1.0),
        ]
        for rid, tax_type, amount in rows:
            conn.execute(
                text(
                    "INSERT INTO tax_records (id, vin, date, tax_type, amount) "
                    "VALUES (:id, 'CARVIN00000000001', '2026-01-15', :tax_type, :amount)"
                ),
                {"id": rid, "tax_type": tax_type, "amount": amount},
            )


def _types(engine: Engine) -> dict[int, str | None]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, tax_type FROM tax_records ORDER BY id")).all()
    return {row[0]: row[1] for row in rows}


def _has_check(dialect: str, engine: Engine) -> bool:
    with engine.connect() as conn:
        if dialect == "sqlite":
            ddl = conn.execute(
                text("SELECT sql FROM sqlite_master WHERE type='table' AND name='tax_records'")
            ).scalar()
            return "CHECK" in (ddl or "").upper()
        count = conn.execute(
            text(
                "SELECT COUNT(*) FROM pg_constraint WHERE conrelid = 'tax_records'::regclass "
                "AND contype = 'c' AND pg_get_constraintdef(oid) LIKE '%tax_type%'"
            )
        ).scalar()
        return bool(count)


def test_146_drops_the_check_and_rewrites_the_legacy_values(engine_for_migration):
    dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    assert _has_check(dialect, engine)

    _load().upgrade(engine)

    assert not _has_check(dialect, engine)
    assert _types(engine) == {
        1: "registration",
        2: "inspection",
        3: "property_tax",
        4: "tolls",
        5: None,
    }
    # A code the CHECK would have refused now inserts.
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tax_records (id, vin, date, tax_type, amount) "
                "VALUES (6, 'CARVIN00000000001', '2026-02-01', 'co2_malus', 300)"
            )
        )
    assert _types(engine)[6] == "co2_malus"
    # The index survived.
    names = {ix["name"] for ix in inspect(engine).get_indexes("tax_records")}
    assert "idx_tax_records_vin" in names
    # The foreign key still holds.
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            if dialect == "sqlite":
                conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.execute(
                text(
                    "INSERT INTO tax_records (id, vin, date, amount) "
                    "VALUES (7, 'NOSUCHVIN00000001', '2026-02-01', 1)"
                )
            )


def test_146_is_idempotent(engine_for_migration):
    dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    mod = _load()
    mod.upgrade(engine)
    before = _types(engine)
    mod.upgrade(engine)
    assert _types(engine) == before
    assert not _has_check(dialect, engine)


def test_146_rewrites_values_on_a_table_without_the_check(engine_for_migration):
    """A create_all database from this release has no CHECK but a restored
    backup may still carry the display strings."""
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine, with_check=False)
    _load().upgrade(engine)
    assert _types(engine)[3] == "property_tax"


def test_146_leaves_an_unknown_value_alone(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine, with_check=False)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tax_records (id, vin, date, tax_type, amount) "
                "VALUES (9, 'CARVIN00000000001', '2026-02-01', 'Income Tax', 1)"
            )
        )
    _load().upgrade(engine)
    assert _types(engine)[9] == "Income Tax"


def test_146_missing_table_skips(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _load().upgrade(engine)
    assert not inspect(engine).has_table("tax_records")


def test_146_is_not_fatal():
    assert _load().FATAL is False

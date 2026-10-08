"""Migration 149: European insurance formulas and the no-claims class (#211).

Parameterised over SQLite and PostgreSQL via `engine_for_migration`: the
policy_type CHECK goes (a « Third Party » row can then be written), the
`no_claims_class` column appears, the unique constraint, the indexes and
the rows of the two child tables survive the SQLite rebuild, and a second
run changes nothing.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

import app.migrations as _m

_NAME = "149_insurance_eu_policy_types"
_CHECK = (
    "CONSTRAINT check_policy_vehicle_type CHECK (policy_type IN ('Liability', "
    "'Comprehensive', 'Collision', 'Full Coverage', 'Minimum', 'Other'))"
)


def _load(name: str = _NAME):
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_tables(engine: Engine, *, with_check: bool = True) -> None:
    check = f", {_CHECK}" if with_check else ""
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY, nickname VARCHAR(100))")
        )
        conn.execute(
            text(
                "CREATE TABLE insurance_policies (id INTEGER PRIMARY KEY, "
                "provider VARCHAR(100) NOT NULL, policy_number VARCHAR(50) NOT NULL)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE insurance_policy_vehicles ("
                "id INTEGER PRIMARY KEY, "
                "policy_id INTEGER NOT NULL REFERENCES insurance_policies(id) ON DELETE CASCADE, "
                "vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE, "
                "policy_type VARCHAR(30) NOT NULL, premium_share NUMERIC(12, 2), "
                "deductible NUMERIC(12, 2), notes TEXT, effective_to DATE, "
                "CONSTRAINT uq_insurance_policy_vehicle UNIQUE (policy_id, vin)"
                f"{check})"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX idx_insurance_policy_vehicles_vin ON insurance_policy_vehicles (vin)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX idx_insurance_policy_vehicles_policy "
                "ON insurance_policy_vehicles (policy_id)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE insurance_policy_fields (id INTEGER PRIMARY KEY, "
                "policy_id INTEGER NOT NULL REFERENCES insurance_policies(id) ON DELETE CASCADE, "
                "policy_vehicle_id INTEGER REFERENCES insurance_policy_vehicles(id) "
                "ON DELETE CASCADE, label VARCHAR(60) NOT NULL, value VARCHAR(255) NOT NULL)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE insurance_coverages (id INTEGER PRIMARY KEY, "
                "policy_vehicle_id INTEGER NOT NULL REFERENCES insurance_policy_vehicles(id) "
                "ON DELETE CASCADE, coverage_key VARCHAR(40) NOT NULL, "
                "CONSTRAINT uq_insurance_coverage UNIQUE (policy_vehicle_id, coverage_key))"
            )
        )
        conn.execute(text("INSERT INTO vehicles (vin, nickname) VALUES ('CARVIN00000000001', 'A')"))
        conn.execute(
            text(
                "INSERT INTO insurance_policies (id, provider, policy_number) VALUES (1, 'MAIF', 'P')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO insurance_policy_vehicles (id, policy_id, vin, policy_type, deductible) "
                "VALUES (1, 1, 'CARVIN00000000001', 'Full Coverage', 300.00)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO insurance_policy_fields (id, policy_id, policy_vehicle_id, label, value) "
                "VALUES (1, 1, 1, 'Agent', 'Someone')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO insurance_coverages (id, policy_vehicle_id, coverage_key) "
                "VALUES (1, 1, 'glass')"
            )
        )


def _insert_link(engine: Engine, link_id: int, policy_type: str, vin: str = "CARVIN00000000001"):
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO insurance_policy_vehicles (id, policy_id, vin, policy_type) "
                "VALUES (:id, 1, :vin, :policy_type)"
            ),
            {"id": link_id, "vin": vin, "policy_type": policy_type},
        )


def test_149_drops_the_check_and_adds_the_column(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    with pytest.raises(IntegrityError):
        _insert_link(engine, 2, "Third Party", vin="CARVIN00000000001")

    _load().upgrade(engine)

    cols = {c["name"]: c for c in inspect(engine).get_columns("insurance_policy_vehicles")}
    assert "no_claims_class" in cols
    assert cols["no_claims_class"]["nullable"] is True
    # The CHECK is gone: a European formula can be written…
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO vehicles (vin, nickname) VALUES ('CARVIN00000000002', 'B')"))
    _insert_link(engine, 2, "Third Party Extended", vin="CARVIN00000000002")
    # …and the unique constraint still holds.
    with pytest.raises(IntegrityError):
        _insert_link(engine, 3, "Third Party", vin="CARVIN00000000002")
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, policy_type, deductible, no_claims_class FROM insurance_policy_vehicles "
                "ORDER BY id"
            )
        ).all()
        children = conn.execute(
            text(
                "SELECT (SELECT COUNT(*) FROM insurance_policy_fields WHERE policy_vehicle_id = 1), "
                "(SELECT COUNT(*) FROM insurance_coverages WHERE policy_vehicle_id = 1)"
            )
        ).one()
    assert [(r[0], r[1], float(r[2]) if r[2] is not None else None, r[3]) for r in rows] == [
        (1, "Full Coverage", 300.0, None),
        (2, "Third Party Extended", None, None),
    ]
    # The rows pointing at the links are still there and still point at them.
    assert tuple(children) == (1, 1)
    names = {index["name"] for index in inspect(engine).get_indexes("insurance_policy_vehicles")}
    assert {"idx_insurance_policy_vehicles_vin", "idx_insurance_policy_vehicles_policy"} <= names


def test_149_is_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    mod = _load()
    mod.upgrade(engine)
    mod.upgrade(engine)
    names = [c["name"] for c in inspect(engine).get_columns("insurance_policy_vehicles")]
    assert names.count("no_claims_class") == 1
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM insurance_policy_vehicles")).scalar() == 1


def test_149_adds_the_column_on_a_table_without_the_check(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine, with_check=False)
    _load().upgrade(engine)
    names = [c["name"] for c in inspect(engine).get_columns("insurance_policy_vehicles")]
    assert "no_claims_class" in names
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO vehicles (vin, nickname) VALUES ('CARVIN00000000002', 'B')"))
    _insert_link(engine, 2, "Third Party", vin="CARVIN00000000002")


def test_149_missing_table_skips(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _load().upgrade(engine)
    assert not inspect(engine).has_table("insurance_policy_vehicles")


def test_149_is_fatal():
    assert _load().FATAL is True


def test_149_sqlite_keeps_the_foreign_keys_whole(tmp_path: Path) -> None:
    """After the rebuild the child tables' references resolve, and the
    column is declared with its type."""
    db_file = tmp_path / "m149.db"
    engine = create_engine(f"sqlite:///{db_file}")
    _make_tables(engine)
    _load().upgrade(engine)
    conn = sqlite3.connect(str(db_file))
    conn.execute("PRAGMA foreign_keys=ON")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    cols = {r[1]: r for r in conn.execute("PRAGMA table_info(insurance_policy_vehicles)")}
    assert cols["no_claims_class"][2].upper() == "VARCHAR(10)"
    ddl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='insurance_policy_vehicles'"
    ).fetchone()[0]
    assert "check_policy_vehicle_type" not in ddl
    assert "uq_insurance_policy_vehicle" in ddl
    conn.close()

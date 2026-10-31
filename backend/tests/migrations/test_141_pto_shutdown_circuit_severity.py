"""Migration 141: the PTO shutdown circuit codes come off critical (S1d-06, R1).

P251D/E/F read "PTO Engine Shutdown Circuit ..." and the shutdown rule took
them for a forced shutdown. The shipped file has the new tier now; 141 moves
the definitions and the vehicle DTCs that copied the old one.
"""

import importlib.util
import json
import logging
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest
from sqlalchemy import Engine, Table, create_engine, text

import app.migrations as _m
from app.models.dtc_definition import DTCDefinition
from app.models.vehicle_dtc import VehicleDTC

pytestmark = pytest.mark.migrations

_NAME = "141_pto_shutdown_circuit_severity"
_DATA = Path(_m.__file__).resolve().parent.parent / "data" / "dtc_definitions.json"
_VIN = "B10MIG14100000001"
_VIN2 = "B10MIG14100000002"
_PTO = ("P251D", "P251E", "P251F")


def _load() -> ModuleType:
    """Load the migration module by file, as the runner does."""
    path = Path(_m.__file__).parent / f"{_NAME}.py"
    spec = importlib.util.spec_from_file_location(_NAME, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_tables(engine: Engine) -> None:
    """dtc_definitions and vehicle_dtcs in their create_all shape, over a stub vehicles table."""
    cast(Table, DTCDefinition.__table__).create(engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY)"))
        conn.execute(text("INSERT INTO vehicles (vin) VALUES (:a), (:b)"), {"a": _VIN, "b": _VIN2})
    cast(Table, VehicleDTC.__table__).create(engine)


def _seed(engine: Engine) -> None:
    """The pre-141 state: three PTO codes at critical/4 plus two real shutdowns.

    Vehicle DTCs: P251D copied critical (active), P251F copied critical (cleared,
    history), P251E set to info by hand, P23A9 a real shutdown at critical, and
    a second P251D on another vehicle already at warning.
    """
    _make_tables(engine)
    defs = [
        ("P251D", "PTO Engine Shutdown Circuit/Open"),
        ("P251E", "PTO Engine Shutdown Circuit Low"),
        ("P251F", "PTO Engine Shutdown Circuit High"),
        ("P23A9", "Communication Fault - Forced Engine Shutdown"),
        ("U3001", "Control Module Improper Shutdown Performance"),
    ]
    dtcs = [
        (_VIN, "P251D", "critical", True),
        (_VIN, "P251F", "critical", False),
        (_VIN, "P251E", "info", True),
        (_VIN, "P23A9", "critical", True),
        (_VIN2, "P251D", "warning", True),
    ]
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO dtc_definitions (code, description, category, severity, "
                "estimated_severity_level, is_emissions_related) "
                "VALUES (:c, :d, 'powertrain', 'critical', 4, :e)"
            ),
            [{"c": c, "d": d, "e": False} for c, d in defs],
        )
        conn.execute(
            text(
                "INSERT INTO vehicle_dtcs (vin, device_id, code, description, severity, "
                "first_seen, last_seen, is_active) VALUES (:v, 'dev1', :c, NULL, :s, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, :a)"
            ),
            [{"v": v, "c": c, "s": s, "a": a} for v, c, s, a in dtcs],
        )


def _definitions(engine: Engine) -> dict[str, tuple[str, int]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT code, severity, estimated_severity_level FROM dtc_definitions")
        ).all()
    return {r[0]: (r[1], r[2]) for r in rows}


def _vehicle_dtcs(engine: Engine) -> dict[tuple[str, str], str]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT vin, code, severity FROM vehicle_dtcs")).all()
    return {(r[0], r[1]): r[2] for r in rows}


def _upgrade(engine: Engine) -> None:
    """Run it the way the runner does: on one connection, in one transaction."""
    with engine.begin() as conn:
        _load().upgrade(conn=conn)


def test_the_new_tier_is_the_shipped_files():
    # main: FileNotFoundError, no migration 141. After that, this is what keeps
    # the migration's constants and a regenerated file from drifting apart.
    mod = _load()
    file = {e["code"]: e for e in json.loads(_DATA.read_text(encoding="utf-8"))}
    assert mod.CODES == _PTO
    for code in _PTO:
        assert (file[code]["severity"], file[code]["estimated_severity_level"]) == (
            mod.NEW_SEVERITY,
            mod.NEW_LEVEL,
        ), code
    assert (mod.NEW_SEVERITY, mod.NEW_LEVEL) == ("warning", 2)


def test_the_migration_is_not_fatal():
    # guard: a failed 141 leaves three codes one tier too loud, not a broken app.
    assert not getattr(_load(), "FATAL", False)


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_pto_codes_move_and_everything_else_stays(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _seed(engine)

    _upgrade(engine)

    # main: FileNotFoundError, no migration 141
    assert _definitions(engine) == {
        "P251D": ("warning", 2),
        "P251E": ("warning", 2),
        "P251F": ("warning", 2),
        "P23A9": ("critical", 4),
        "U3001": ("critical", 4),
    }
    assert _vehicle_dtcs(engine) == {
        (_VIN, "P251D"): "warning",
        (_VIN, "P251F"): "warning",
        (_VIN, "P251E"): "info",
        (_VIN, "P23A9"): "critical",
        (_VIN2, "P251D"): "warning",
    }


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_a_second_run_changes_nothing(engine_for_migration, caplog: pytest.LogCaptureFixture):
    _dialect, engine, _url = engine_for_migration
    _seed(engine)
    _upgrade(engine)
    before = (_definitions(engine), _vehicle_dtcs(engine))
    caplog.set_level(logging.INFO)

    _upgrade(engine)

    assert (_definitions(engine), _vehicle_dtcs(engine)) == before
    assert "141: 0 vehicle DTC(s) moved off critical" in caplog.text


def test_missing_tables_are_skipped(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    engine = create_engine("sqlite://")
    try:
        _upgrade(engine)
    finally:
        engine.dispose()
    assert "141: vehicle_dtcs missing" in caplog.text
    assert "141: dtc_definitions missing" in caplog.text


def test_the_runner_takes_the_atomic_path(tmp_path: Path) -> None:
    # guard: kills an upgrade(engine) 141, which the runner would stamp in a
    # second transaction after the UPDATEs committed.
    from app.migrations.runner import MigrationRunner

    runner = MigrationRunner(f"sqlite:///{tmp_path / 'r.db'}", Path(_m.__file__).parent)
    try:
        assert runner._takes_conn(_load())
    finally:
        runner.engine.dispose()

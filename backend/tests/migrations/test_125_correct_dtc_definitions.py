"""Migration 125: correct dtc_definitions by code and fill DTCs recorded without one (1d).

033 seeded a table whose generic P0 descriptions were shifted and whose maker
rows named no maker. 125 makes the table match the shipped file in one
transaction: delete what the file doesn't carry, upsert by code, re-apply 091's
enrichment, and fill vehicle_dtcs rows recorded while the table was empty.
The tables come from the models' create_all shape, which is what prod and
init_db have. Parameterised over SQLite and PostgreSQL via `engine_for_migration`.
"""

import importlib.util
import json
import logging
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest
from sqlalchemy import Engine, Table, inspect, text

import app.migrations as _m
from app.models.dtc_definition import DTCDefinition
from app.models.vehicle_dtc import VehicleDTC

pytestmark = pytest.mark.migrations

_NAME = "125_correct_dtc_definitions"
_DATA = Path(_m.__file__).resolve().parent.parent / "data" / "dtc_definitions.json"

# What prod's shifted table said for these codes.
_SHIFTED_P0300 = "Cylinder 12 Contribution/Range Fault"
_SHIFTED_P0420 = 'Secondary Air Injection System Relay "B" Circuit Malfunction'
_MAKER_P1000 = "OBD-II Monitor Testing Not Complete"
_NOT_CORRECTED = "125: DTC definitions not corrected"


def _load(name: str = _NAME) -> ModuleType:
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _file() -> dict[str, dict[str, object]]:
    return {e["code"]: e for e in json.loads(_DATA.read_text(encoding="utf-8"))}


def _make_tables(engine: Engine) -> None:
    """dtc_definitions in its create_all shape, plus vehicle_dtcs over a stub vehicles table."""
    cast(Table, DTCDefinition.__table__).create(engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY)"))
        conn.execute(text("INSERT INTO vehicles (vin) VALUES ('VDTC125TEST000001')"))
    cast(Table, VehicleDTC.__table__).create(engine)


def _define(engine: Engine, code: str, description: str, causes: str | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO dtc_definitions (code, description, category, severity, "
                "estimated_severity_level, is_emissions_related, common_causes) "
                "VALUES (:c, :d, 'powertrain', 'warning', 2, :e, :cc)"
            ),
            {"c": code, "d": description, "e": False, "cc": causes},
        )


def _vehicle_dtc(engine: Engine, code: str, description: str | None, severity: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO vehicle_dtcs (vin, device_id, code, description, severity, "
                "first_seen, last_seen, is_active) VALUES ('VDTC125TEST000001', 'dev1', :c, :d, :s, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, :a)"
            ),
            {"c": code, "d": description, "s": severity, "a": True},
        )


def _count(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM dtc_definitions")).scalar_one()


def _definition(engine: Engine, code: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM dtc_definitions WHERE code = :c"), {"c": code}
        ).one_or_none()
    return dict(row._mapping) if row is not None else None


def _description(engine: Engine, code: str) -> str | None:
    row = _definition(engine, code)
    return None if row is None else row["description"]


def _vehicle_row(engine: Engine, code: str) -> tuple[str | None, str]:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT description, severity FROM vehicle_dtcs WHERE code = :c"), {"c": code}
        ).one()
    return row[0], row[1]


def _dump(engine: Engine) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    with engine.connect() as conn:
        definitions = conn.execute(text("SELECT * FROM dtc_definitions ORDER BY code")).all()
        vehicle_dtcs = conn.execute(text("SELECT * FROM vehicle_dtcs ORDER BY id")).all()
    return [tuple(r) for r in definitions], [tuple(r) for r in vehicle_dtcs]


def _errors(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]


def test_125_corrects_a_shifted_table(engine_for_migration: tuple[str, Engine, str]) -> None:
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    _define(engine, "P0300", _SHIFTED_P0300)
    _define(engine, "P0420", _SHIFTED_P0420)
    _define(engine, "P1000", _MAKER_P1000)

    _load().upgrade(engine)

    assert "Random/Multiple Cylinder Misfire" in (_description(engine, "P0300") or "")
    assert "Catalyst System Efficiency Below Threshold Bank 1" in (
        _description(engine, "P0420") or ""
    )
    assert _definition(engine, "P1000") is None
    assert _count(engine) == len(_file())

    p0300 = _definition(engine, "P0300")
    assert p0300 is not None
    wanted = _file()["P0300"]
    assert p0300["severity"] == wanted["severity"]
    assert p0300["estimated_severity_level"] == wanted["estimated_severity_level"]
    assert bool(p0300["is_emissions_related"]) == wanted["is_emissions_related"]
    # 091's enrichment lands in the same transaction as the correction.
    assert p0300["common_causes"] is not None


def test_125_keeps_enrichment_it_does_not_own(
    engine_for_migration: tuple[str, Engine, str],
) -> None:
    """P0101 isn't one of 091's 8 codes, so neither the upsert nor the enrichment touches its causes."""
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    _define(engine, "P0101", "old", causes='["kept"]')

    _load().upgrade(engine)

    p0101 = _definition(engine, "P0101")
    assert p0101 is not None
    assert p0101["description"] == _file()["P0101"]["description"]
    assert p0101["common_causes"] == '["kept"]'


def test_125_seeds_an_empty_table(
    engine_for_migration: tuple[str, Engine, str], caplog: pytest.LogCaptureFixture
) -> None:
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    file = _file()

    with caplog.at_level(logging.INFO):
        _load().upgrade(engine)

    assert _count(engine) == len(file)
    p0300 = _definition(engine, "P0300")
    assert p0300 is not None
    assert p0300["common_causes"] is not None
    assert (
        f"125: dtc_definitions now {len(file)} codes ({len(file)} added, 0 removed); "
        "0 vehicle DTCs filled"
    ) in caplog.text

    # Raw SQLite hands back 1/0 and PG hands back bool, so compare truthiness.
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT code, is_emissions_related FROM dtc_definitions")).all()
    truthy = {code for code, flag in rows if bool(flag)}
    expected = {code for code, e in file.items() if e["is_emissions_related"]}
    assert expected
    assert truthy == expected


def test_125_fills_vehicle_dtcs_recorded_without_a_definition(
    engine_for_migration: tuple[str, Engine, str],
) -> None:
    _dialect, engine, _url = engine_for_migration
    file = _file()
    # The generator makes "Intermittent" info, so P0104 shows the severity being filled.
    assert file["P0104"]["severity"] != "warning"
    assert "P1131" not in file
    _make_tables(engine)
    _vehicle_dtc(engine, "P0104", None, "warning")
    _vehicle_dtc(engine, "P0300", None, "critical")
    _vehicle_dtc(engine, "P0171", "My note", "warning")
    _vehicle_dtc(engine, "P1131", None, "warning")

    _load().upgrade(engine)

    assert _vehicle_row(engine, "P0104") == (
        file["P0104"]["description"],
        file["P0104"]["severity"],
    )
    # A severity other than the no-definition default was set on purpose.
    assert _vehicle_row(engine, "P0300") == (file["P0300"]["description"], "critical")
    assert _vehicle_row(engine, "P0171") == ("My note", "warning")
    assert _vehicle_row(engine, "P1131") == (None, "warning")


def test_125_is_idempotent(engine_for_migration: tuple[str, Engine, str]) -> None:
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    _define(engine, "P0300", _SHIFTED_P0300)
    _vehicle_dtc(engine, "P0104", None, "warning")
    mod = _load()

    mod.upgrade(engine)
    first = _dump(engine)
    assert _description(engine, "P0300") == _file()["P0300"]["description"]
    assert _vehicle_row(engine, "P0104")[0] == _file()["P0104"]["description"]

    mod.upgrade(engine)

    assert _dump(engine) == first


def test_fresh_install_chain(engine_for_migration: tuple[str, Engine, str]) -> None:
    """A fresh install runs 033, 091, 125 in order; 033 alone seeds the shipped file."""
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    file = _file()

    _load("033_seed_dtc_definitions").upgrade(engine)
    assert _count(engine) == len(file)
    _load("091_dtc_phase2_enrichment").upgrade(engine)
    _load().upgrade(engine)

    assert _count(engine) == len(file)
    p0300 = _definition(engine, "P0300")
    assert p0300 is not None
    assert p0300["description"] == file["P0300"]["description"]
    assert p0300["common_causes"] is not None


def test_125_without_the_table_skips(
    engine_for_migration: tuple[str, Engine, str], caplog: pytest.LogCaptureFixture
) -> None:
    _dialect, engine, _url = engine_for_migration

    with caplog.at_level(logging.INFO):
        _load().upgrade(engine)

    assert not inspect(engine).has_table("dtc_definitions")
    assert _errors(caplog) == []


def test_125_without_vehicle_dtcs_still_corrects(
    engine_for_migration: tuple[str, Engine, str], caplog: pytest.LogCaptureFixture
) -> None:
    _dialect, engine, _url = engine_for_migration
    cast(Table, DTCDefinition.__table__).create(engine)
    _define(engine, "P0300", _SHIFTED_P0300)

    with caplog.at_level(logging.INFO):
        _load().upgrade(engine)

    assert _description(engine, "P0300") == _file()["P0300"]["description"]
    assert not inspect(engine).has_table("vehicle_dtcs")
    assert _errors(caplog) == []


def _bad_content(case: str) -> str | None:
    """A broken data or enrichment file; None means the file is missing."""
    if case == "not_json":
        return "{"
    if case == "missing":
        return None
    entry = dict(_file()["P0300"])
    if case == "missing_severity":
        del entry["severity"]
    elif case == "null_level":
        entry["estimated_severity_level"] = None
    else:
        raise AssertionError(case)
    return json.dumps([entry])


@pytest.mark.parametrize(
    ("attr", "case"),
    [
        ("_DATA", "not_json"),
        ("_DATA", "missing_severity"),
        ("_DATA", "null_level"),
        ("_DATA", "missing"),
        ("_ENRICHMENT", "not_json"),
        ("_ENRICHMENT", "missing"),
    ],
)
def test_125_swallows_a_bad_data_file(
    engine_for_migration: tuple[str, Engine, str],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    attr: str,
    case: str,
) -> None:
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    _define(engine, "P0300", _SHIFTED_P0300)
    mod = _load()
    bad = tmp_path / "bad.json"
    content = _bad_content(case)
    if content is not None:
        bad.write_text(content, encoding="utf-8")
    setattr(mod, attr, bad)

    with caplog.at_level(logging.INFO):
        mod.upgrade(engine)

    assert _description(engine, "P0300") == _SHIFTED_P0300
    assert _count(engine) == 1
    assert any(_NOT_CORRECTED in message for message in _errors(caplog))


@pytest.mark.parametrize("statement", ["_ENRICH", "_FILL_VEHICLE_DTCS"])
def test_125_rolls_back_a_failure_after_the_writes_start(
    engine_for_migration: tuple[str, Engine, str],
    caplog: pytest.LogCaptureFixture,
    statement: str,
) -> None:
    """The DELETE and the upsert have run when this statement fails; all of it rolls back."""
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    _define(engine, "P0300", _SHIFTED_P0300)
    _define(engine, "P1000", _MAKER_P1000)
    _vehicle_dtc(engine, "P0104", None, "warning")
    mod = _load()
    setattr(mod, statement, text("UPDATE no_such_table SET x = 1"))

    with caplog.at_level(logging.INFO):
        mod.upgrade(engine)

    assert _description(engine, "P1000") == _MAKER_P1000
    assert _description(engine, "P0300") == _SHIFTED_P0300
    assert _count(engine) == 2
    assert _vehicle_row(engine, "P0104") == (None, "warning")
    assert any(_NOT_CORRECTED in message for message in _errors(caplog))


def test_125_is_not_fatal() -> None:
    assert _load().FATAL is False

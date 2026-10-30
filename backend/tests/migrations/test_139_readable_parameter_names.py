"""Migration 139: rows still on their auto name get the readable one (R3, R8).

Covers the shared canonical keys (D2), Torque's own KFF keys (D3) and the two
shipped "(L/100 km)" names, plus the D1b warning for a Torque device whose
history may be stored 1.609x high. Tables are built by hand with only the
columns 139 reads.
"""

import importlib.util
import logging
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError

import app.migrations as _m
from app.migrations.runner import MigrationRunner

pytestmark = pytest.mark.migrations

_NAME = "139_readable_parameter_names"

#: The D2 table, as answered 2026-10-29.
D2 = {
    "COOLANT_TMP": "Coolant temperature",
    "ENGINE_RPM": "Engine RPM",
    "ENGINE_LOAD": "Engine load",
    "INTAKE_PRESSURE": "Intake manifold pressure",
    "INTAKE_TEMP": "Intake air temperature",
    "TIMING_ADVANCE": "Timing advance",
    "MAF": "Mass air flow",
    "THROTTLE": "Throttle position",
    "RUN_TIME": "Engine run time",
    "FUEL": "Fuel level",
    "CONTROL_MODULE_VOLTAGE": "Control module voltage",
    "AMBIENT_TEMP": "Ambient air temperature",
    "OIL_TEMP": "Engine oil temperature",
    "SPEED": "Speed",
    "TORQUE_ODOMETER": "Odometer (Torque)",
}


def _load(name: str = _NAME) -> ModuleType:
    """Load a migration module by file, as the runner does."""
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _title(key: str) -> str:
    return key.replace("_", " ").title()


def _pk(engine: Engine) -> str:
    return (
        "SERIAL PRIMARY KEY"
        if engine.dialect.name == "postgresql"
        else "INTEGER PRIMARY KEY AUTOINCREMENT"
    )


def _make_tables(engine: Engine, name_width: int = 100) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS livelink_parameters"))
        conn.execute(text("DROP TABLE IF EXISTS livelink_devices"))
        conn.execute(
            text(
                f"CREATE TABLE livelink_parameters (id {_pk(engine)},"
                " param_key VARCHAR(100) NOT NULL UNIQUE,"
                f" display_name VARCHAR({name_width}))"
            )
        )
        conn.execute(
            text(
                f"CREATE TABLE livelink_devices (id {_pk(engine)},"
                " device_id VARCHAR(20) NOT NULL UNIQUE, kind VARCHAR(20) NOT NULL,"
                " odometer_unit VARCHAR(4), odometer_param_key VARCHAR(100))"
            )
        )


def _add(engine: Engine, rows: dict[str, str | None]) -> None:
    with engine.begin() as conn:
        for key, name in rows.items():
            conn.execute(
                text("INSERT INTO livelink_parameters (param_key, display_name) VALUES (:k, :n)"),
                {"k": key, "n": name},
            )


def _names(engine: Engine) -> dict[str, str | None]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT param_key, display_name FROM livelink_parameters")).all()
    return {k: n for k, n in rows}


def _add_device(
    engine: Engine, device_id: str, kind: str, unit: str | None, key: str | None
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO livelink_devices (device_id, kind, odometer_unit, odometer_param_key)"
                " VALUES (:d, :k, :u, :p)"
            ),
            {"d": device_id, "k": kind, "u": unit, "p": key},
        )


def _devices(engine: Engine) -> list[tuple[str, str, str | None, str | None]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT device_id, kind, odometer_unit, odometer_param_key"
                " FROM livelink_devices ORDER BY device_id"
            )
        ).all()
    return [(r[0], r[1], r[2], r[3]) for r in rows]


# --- the frozen tables ------------------------------------------------------


def test_the_migration_is_not_fatal():
    # Passes once the file exists. Kills a 139 marked FATAL: a rename isn't
    # worth keeping the app down for.
    assert not getattr(_load(), "FATAL", False)


def test_the_frozen_d2_table_is_the_answered_one():
    assert _load()._READABLE == D2


def test_every_frozen_title_is_what_title_case_gives():
    """str.title() capitalises after a digit, so KFF123A is "Kff123A" (F1-6)."""
    mod = _load()
    titles = {**mod._TITLES_D2, **mod._TITLES_KFF}
    assert set(titles) == set(mod._READABLE) | set(mod._KFF_NAMES)
    for key, title in titles.items():
        assert title == _title(key), key
    assert titles["KFF123A"] == "Kff123A"
    assert titles["KFF124D"] == "Kff124D"


def test_the_kff_names_carry_the_tq_l4_spelling():
    mod = _load()
    assert mod._KFF_NAMES["KFF1207"] == "Instant economy (L/100km)"
    assert mod._KFF_NAMES["KFF1208"] == "Trip economy (L/100km)"
    assert mod._KFF_NAMES["KFF1238"] == "OBD adapter voltage"
    assert mod._KFF_NAMES["KFF123A"] == "GPS satellites"
    assert mod._SHIPPED == {
        "KFF1207": "Instant economy (L/100 km)",
        "KFF1208": "Trip economy (L/100 km)",
    }


def test_every_frozen_name_fits_the_column():
    mod = _load()
    names = [*mod._READABLE.values(), *mod._KFF_NAMES.values()]
    assert max(len(n) for n in names) <= 100


# --- the renames ------------------------------------------------------------


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_rows_on_the_auto_name_get_the_readable_one(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    rows: dict[str, str | None] = {key: _title(key) for key in D2}
    rows["FUEL"] = None  # no name at all reads as auto too
    _add(engine, rows)

    _load().upgrade(engine)

    assert _names(engine) == D2


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_the_names_130_wrote_move_too(engine_for_migration):
    """130 still writes its frozen "Coolant Tmp" and "Engine Rpm"; 139 is what moves them."""
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    frozen_130 = _load("130_move_torque_one_digit_pid_keys")._NEW_ROWS
    shared = {key: row[0] for key, row in frozen_130.items() if key in D2}
    assert shared["COOLANT_TMP"] == "Coolant Tmp"
    assert shared["ENGINE_RPM"] == "Engine Rpm"
    _add(engine, shared)

    _load().upgrade(engine)

    assert _names(engine) == {key: D2[key] for key in shared}


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_a_name_someone_set_stays(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    _add(
        engine,
        {
            "COOLANT_TMP": "My coolant",
            "KFF1238": "Adapter volts",
            "KFF1201": "Instant economy (mpg)",  # already the readable one
            "SOME_OTHER_KEY": "Some Other Key",  # not 139's key
        },
    )

    _load().upgrade(engine)

    assert _names(engine) == {
        "COOLANT_TMP": "My coolant",
        "KFF1238": "Adapter volts",
        "KFF1201": "Instant economy (mpg)",
        "SOME_OTHER_KEY": "Some Other Key",
    }


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_kff_rows_on_their_auto_or_shipped_name_move(engine_for_migration):
    """The shipped "(L/100 km)" names only move here: the upload rule counts them as set (D3)."""
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    _add(
        engine,
        {
            "KFF1238": "Kff1238",
            "KFF123A": "Kff123A",
            "KFF124D": None,
            "KFF1207": "Instant economy (L/100 km)",
            "KFF1208": "Trip economy (L/100 km)",
            "KFF1205": "Kff1205",
        },
    )

    _load().upgrade(engine)

    assert _names(engine) == {
        "KFF1238": "OBD adapter voltage",
        "KFF123A": "GPS satellites",
        "KFF124D": "Air-fuel ratio, commanded",
        "KFF1207": "Instant economy (L/100km)",
        "KFF1208": "Trip economy (L/100km)",
        "KFF1205": "Trip economy (mpg)",
    }


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_the_shipped_name_only_moves_on_its_own_key(engine_for_migration):
    """KFF1201 on the KFF1207 shipped name is a name someone set, not a stale one."""
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    _add(engine, {"KFF1201": "Instant economy (L/100 km)"})
    _load().upgrade(engine)
    assert _names(engine) == {"KFF1201": "Instant economy (L/100 km)"}


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_a_second_run_changes_nothing(engine_for_migration, caplog):
    _dialect, engine, _url = engine_for_migration
    caplog.set_level(logging.INFO)
    _make_tables(engine)
    # SPEED's title is its readable name: rewriting it in place would count as a rename.
    _add(
        engine,
        {
            "COOLANT_TMP": "Coolant Tmp",
            "KFF1207": "Instant economy (L/100 km)",
            "SPEED": None,
        },
    )
    mod = _load()
    mod.upgrade(engine)
    before = _names(engine)
    caplog.clear()
    _add(engine, {"ENGINE_RPM": "My RPM"})
    mod.upgrade(engine)
    assert _names(engine) == {**before, "ENGINE_RPM": "My RPM"}
    assert "139: renamed 0 parameter(s)" in caplog.text


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_missing_tables_are_skipped(engine_for_migration, caplog):
    """Skipped on purpose, not caught by the error log: without the checks the SQL fails."""
    _dialect, engine, _url = engine_for_migration
    caplog.set_level(logging.INFO)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS livelink_parameters"))
        conn.execute(text("DROP TABLE IF EXISTS livelink_devices"))

    _load().upgrade(engine)

    assert "139: livelink_parameters missing" in caplog.text
    assert "139: livelink_devices missing" in caplog.text
    assert "ERROR" not in [r.levelname for r in caplog.records]


# --- D1b --------------------------------------------------------------------


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_a_torque_device_on_miles_gets_a_warning_and_nothing_else(engine_for_migration, caplog):
    _dialect, engine, _url = engine_for_migration
    caplog.set_level(logging.INFO)
    _make_tables(engine)
    _add_device(engine, "tq-mi", "torque", "mi", "TORQUE_ODOMETER")  # the one
    _add_device(engine, "tq-km", "torque", "km", "TORQUE_ODOMETER")
    _add_device(engine, "tq-custom", "torque", "mi", "K_CUSTOM_ODO")
    _add_device(engine, "wican-mi", "wican", "mi", "TORQUE_ODOMETER")
    _add_device(engine, "tq-none", "torque", None, None)
    before = _devices(engine)

    _load().upgrade(engine)

    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "tq-mi" in warnings[0]
    assert (
        "python tools/repair_wican_odometer_unit.py --device-id tq-mi --key TORQUE_ODOMETER --to km"
    ) in warnings[0]
    assert _devices(engine) == before


# --- failures ---------------------------------------------------------------


def test_a_failure_is_logged_not_raised(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A non-FATAL failure that raises stops every migration after it, so 139 logs it instead."""
    mod = _load()

    def boom(_engine: Engine) -> None:
        raise OperationalError("UPDATE livelink_parameters", {}, Exception("database is locked"))

    monkeypatch.setattr(mod, "_rename", boom)
    mod.upgrade(create_engine("sqlite://"))
    assert "139: parameter names not updated" in caplog.text


@pytest.mark.parametrize("engine_for_migration", ["pg"], indirect=True)
def test_a_failed_rename_through_the_runner_still_stamps_139(engine_for_migration, caplog):
    """PG only: there a caught error inside the runner's transaction aborts it, and the
    stamp fails with it. 139 runs in its own transaction, so the stamp lands (R8, F1-8).

    The runner loads its own copy of the module, so the failure comes from the
    database: a display_name too narrow for the new name.
    """
    _dialect, engine, url = engine_for_migration
    _make_tables(engine, name_width=5)
    _add(engine, {"COOLANT_TMP": None})
    migrations_dir = Path(_m.__file__).parent
    runner = MigrationRunner(url, migrations_dir)
    runner._ensure_migration_tracking_table()
    with engine.begin() as conn:
        for stem, _path in runner._discover_migrations():
            if stem != _NAME:
                conn.execute(
                    text("INSERT INTO schema_migrations (migration_name) VALUES (:n)"),
                    {"n": stem},
                )

    try:
        runner.run_pending_migrations()
    finally:
        runner.engine.dispose()

    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(m.startswith("139: parameter names not updated") for m in errors), errors
    with engine.connect() as conn:
        applied = set(conn.execute(text("SELECT migration_name FROM schema_migrations")).scalars())
    assert _NAME in applied
    assert _names(engine) == {"COOLANT_TMP": None}

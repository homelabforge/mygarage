"""Migration 165: percentage parameters on other or no category get a real one (B-9).

WiCAN files every % reading under class ``percentage``, and that class used to
land on ``other``. 165 moves those rows by key: fuel keys to ``fuel``, state of
charge and battery keys to ``electrical``, the rest to ``engine``. A category
someone set, and a row on another class, stay as they are.
"""

import pytest
from sqlalchemy import Engine, inspect, text

from tests.migrations._loader import load_migration

pytestmark = pytest.mark.migrations

_NAME = "165_categorize_percentage_parameters"
_BOTH = pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)

#: (param_key, param_class, category) as seeded.
_SEED = [
    ("2F-FUELTANKLEVEL", "percentage", "other"),
    ("FUEL", "percentage", None),
    ("06-SHORTTERMFUELTRIM", "percentage", "other"),
    ("HV_BATT_SOC", "percentage", "other"),
    ("EV_SOC", "percentage", None),
    ("THROTTLE_POS", "percentage", "other"),
    ("04-ENGINELOAD", "percentage", None),
    # The admin endpoint stores an empty string, and the runtime reads it as unset.
    ("ZZ_EMPTY_FUEL", "percentage", ""),
    # The app matches the class case-blind, so 165 does too.
    ("ZZ_PEDAL_D", "Percentage", "other"),
    # Someone filed this one by hand, so it stays.
    ("PEDAL_POS", "percentage", "temperature"),
    # Not a percentage, so 165 doesn't look at it.
    ("9B-CUSTOMSENSOR", "diagnostic", "other"),
    ("ZZ_NO_CLASS", None, "other"),
]

#: Hand-typed on purpose: deriving these from the rule would test it against itself.
_EXPECTED = {
    "2F-FUELTANKLEVEL": "fuel",
    "FUEL": "fuel",
    "06-SHORTTERMFUELTRIM": "fuel",
    "HV_BATT_SOC": "electrical",
    "EV_SOC": "electrical",
    "THROTTLE_POS": "engine",
    "04-ENGINELOAD": "engine",
    "ZZ_EMPTY_FUEL": "fuel",
    "ZZ_PEDAL_D": "engine",
    "PEDAL_POS": "temperature",
    "9B-CUSTOMSENSOR": "other",
    "ZZ_NO_CLASS": "other",
}


def _make_table(engine: Engine) -> None:
    pk = "SERIAL PRIMARY KEY" if engine.dialect.name == "postgresql" else "INTEGER PRIMARY KEY"
    with engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE TABLE livelink_parameters (id {pk},"
                " param_key VARCHAR(100) UNIQUE NOT NULL,"
                " param_class VARCHAR(50), category VARCHAR(50))"
            )
        )
        for key, klass, category in _SEED:
            conn.execute(
                text(
                    "INSERT INTO livelink_parameters (param_key, param_class, category)"
                    " VALUES (:k, :c, :cat)"
                ),
                {"k": key, "c": klass, "cat": category},
            )


def _categories(engine: Engine) -> dict[str, str | None]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT param_key, category FROM livelink_parameters")).all()
    return {k: c for k, c in rows}


def test_the_migration_is_not_fatal() -> None:
    # Nothing reads category yet, so a failure isn't worth keeping the app down.
    assert not getattr(load_migration(_NAME), "FATAL", False)


@_BOTH
def test_percentage_rows_get_a_category_by_key(
    engine_for_migration: tuple[str, Engine, str],
) -> None:
    _dialect, engine, _url = engine_for_migration
    _make_table(engine)

    load_migration(_NAME).upgrade(engine)

    assert _categories(engine) == _EXPECTED


@_BOTH
def test_a_second_run_changes_nothing(engine_for_migration: tuple[str, Engine, str]) -> None:
    _dialect, engine, _url = engine_for_migration
    _make_table(engine)
    mod = load_migration(_NAME)
    mod.upgrade(engine)
    first = _categories(engine)

    mod.upgrade(engine)

    assert _categories(engine) == first == _EXPECTED


@_BOTH
def test_no_table_is_a_no_op(engine_for_migration: tuple[str, Engine, str]) -> None:
    _dialect, engine, _url = engine_for_migration
    load_migration(_NAME).upgrade(engine)
    assert not inspect(engine).has_table("livelink_parameters")


def test_the_frozen_rule_matches_the_runtime_one_today() -> None:
    """Drift guard for now: 165 keeps its own copy of the rule, which may fall
    behind the runtime one later. The migration must not change if it does."""
    from app.services.telemetry.parameters import TelemetryParametersMixin

    mod = load_migration(_NAME)
    # The rule never touches the session, so skip building one.
    svc = TelemetryParametersMixin.__new__(TelemetryParametersMixin)
    for key, klass, _category in _SEED:
        if klass and klass.lower() == "percentage":
            assert mod._category_for(key) == svc._classify_param(klass, key), key

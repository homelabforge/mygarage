"""Migration 110: widen livelink_devices.kind so 'generic_mqtt' fits.

Builds the PRE-110 shape by hand. The ORM now declares kind as String(20), so a
create_all baseline would start in the POST state and every width assertion
would pass before the migration ran (the same reasoning test_098 states in its
own docstring). A SQLite-only run proves nothing here at all: SQLite does not
enforce VARCHAR length, which is the entire reason this migration exists.
"""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

import app.migrations as _m
from app.models.livelink_device import LiveLinkDevice

pytestmark = pytest.mark.migrations


def _load(name: str):
    """Load a migration module by number-name, as test_098 does."""
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_pre_110_kind_column(engine) -> None:
    """A livelink_devices table whose `kind` is the OLD VARCHAR(10)."""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS livelink_devices"))
        pk = (
            "SERIAL PRIMARY KEY"
            if engine.dialect.name == "postgresql"
            else "INTEGER PRIMARY KEY AUTOINCREMENT"
        )
        conn.execute(
            text(
                f"""
                CREATE TABLE livelink_devices (
                    id {pk},
                    device_id VARCHAR(20) NOT NULL UNIQUE,
                    vin VARCHAR(17),
                    kind VARCHAR(10) NOT NULL DEFAULT 'wican'
                )
                """
            )
        )


def test_model_declares_a_column_wide_enough_for_generic_mqtt():
    col = LiveLinkDevice.__table__.c.kind
    assert col.type.length >= len("generic_mqtt")


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_the_column_is_actually_widened(engine_for_migration):
    """The assertion R1-M1 says was missing: check the DATABASE, not the model."""
    dialect, engine, _url = engine_for_migration
    _make_pre_110_kind_column(engine)

    before = {c["name"]: c for c in inspect(engine).get_columns("livelink_devices")}
    if dialect == "pg":
        assert before["kind"]["type"].length == 10, "fixture must start in the PRE state"

    _load("110_widen_livelink_device_kind").upgrade(engine)

    after = {c["name"]: c for c in inspect(engine).get_columns("livelink_devices")}
    if dialect == "pg":
        assert after["kind"]["type"].length >= len("generic_mqtt")


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_an_existing_generic_mqtt_insert_succeeds_after_upgrade(engine_for_migration):
    """The user-visible symptom: PG rejects the insert until this migration runs."""
    _dialect, engine, _url = engine_for_migration
    _make_pre_110_kind_column(engine)
    _load("110_widen_livelink_device_kind").upgrade(engine)
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO livelink_devices (device_id, kind) VALUES ('gw01', 'generic_mqtt')")
        )
        got = conn.execute(
            text("SELECT kind FROM livelink_devices WHERE device_id = 'gw01'")
        ).scalar_one()
    assert got == "generic_mqtt"


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_migration_is_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_pre_110_kind_column(engine)
    mod = _load("110_widen_livelink_device_kind")
    mod.upgrade(engine)
    mod.upgrade(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("livelink_devices")}
    assert "kind" in cols

"""Migration 112: livelink_devices.odometer_param_key.

ORM-backed behaviour lives in tests/unit/services/test_declared_odometer.py,
not here: `engine_for_migration` drops the PostgreSQL public schema, which
destroys the tables create_all built for any db_session test in this package.
"""

import pytest
from sqlalchemy import inspect, text

from tests.migrations._loader import load_migration

pytestmark = pytest.mark.migrations


def _make_pre_112_table(engine) -> None:
    pk = (
        "SERIAL PRIMARY KEY"
        if engine.dialect.name == "postgresql"
        else "INTEGER PRIMARY KEY AUTOINCREMENT"
    )
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS livelink_devices"))
        conn.execute(
            text(f"CREATE TABLE livelink_devices (id {pk}, device_id VARCHAR(20) NOT NULL UNIQUE)")
        )


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_the_column_is_added_to_an_existing_table(engine_for_migration):
    """create_all never ALTERs an existing table, which is why this is FATAL."""
    _dialect, engine, _url = engine_for_migration
    _make_pre_112_table(engine)
    assert "odometer_param_key" not in {
        c["name"] for c in inspect(engine).get_columns("livelink_devices")
    }, "fixture must start WITHOUT the column"

    mod = load_migration("112_device_odometer_param_key")
    assert mod.FATAL is True, "an add-column migration must halt startup on failure"
    mod.upgrade(engine)
    mod.upgrade(engine)  # idempotent

    assert "odometer_param_key" in {
        c["name"] for c in inspect(engine).get_columns("livelink_devices")
    }


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_existing_rows_get_null_not_a_backfill(engine_for_migration):
    """NULL means 'declares nothing', which keeps existing installs unchanged."""
    _dialect, engine, _url = engine_for_migration
    _make_pre_112_table(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO livelink_devices (device_id) VALUES ('legacy')"))
    load_migration("112_device_odometer_param_key").upgrade(engine)
    with engine.connect() as conn:
        got = conn.execute(
            text("SELECT odometer_param_key FROM livelink_devices WHERE device_id = 'legacy'")
        ).scalar_one()
    assert got is None

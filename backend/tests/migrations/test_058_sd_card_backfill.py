import importlib.util
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

import app.migrations as _m


def _load(name):
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _legacy_devices_table(engine):
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE livelink_devices (id INTEGER PRIMARY KEY, device_id VARCHAR(20))")
        )


def test_058_adds_columns_and_table():
    engine = create_engine("sqlite://")
    _legacy_devices_table(engine)
    _load("058_sd_card_backfill").upgrade(engine)
    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("livelink_devices")}
    assert {"device_address", "sd_backfill_enabled"} <= cols
    assert insp.has_table("sd_log_ingest_state")
    idx = {i["name"] for i in insp.get_indexes("sd_log_ingest_state")}
    assert "uq_sd_log_ingest_device_file" in idx


def test_058_idempotent():
    engine = create_engine("sqlite://")
    _legacy_devices_table(engine)
    mod = _load("058_sd_card_backfill")
    mod.upgrade(engine)
    mod.upgrade(engine)  # no raise


def test_058_ingest_state_autoincrements():
    engine = create_engine("sqlite://")
    _legacy_devices_table(engine)
    _load("058_sd_card_backfill").upgrade(engine)
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO sd_log_ingest_state (device_id, filename) VALUES ('dev1', 'a.db')")
        )
        row = conn.execute(text("SELECT id FROM sd_log_ingest_state")).fetchone()
    assert row is not None
    assert isinstance(row[0], int)
    assert row[0] > 0

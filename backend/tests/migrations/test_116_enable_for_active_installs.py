"""Migration 116: switch LiveLink on for installs already receiving MQTT or Torque data.

Before Plan 3 the master switch gated only the HTTPS route and the periodic
jobs; MQTT and Torque stored data with it off. It now gates everything, so an
install receiving data with the switch off would silently stop on upgrade.
"""

import importlib.util
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text

_MIG = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "migrations"
    / "116_livelink_enable_for_active_installs.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("mig116", _MIG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _engine(engine, settings: dict[str, str | None], devices: list[dict] | None = None):
    """Seed the two tables the migration reads, in DDL both dialects accept."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE settings ("
                "  key VARCHAR(50) PRIMARY KEY,"
                "  value TEXT,"
                "  category VARCHAR(50) DEFAULT 'general',"
                "  description TEXT,"
                "  encrypted BOOLEAN DEFAULT FALSE"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE livelink_devices ("
                "  device_id VARCHAR(20) PRIMARY KEY,"
                "  kind VARCHAR(20) NOT NULL DEFAULT 'wican',"
                "  vin VARCHAR(17),"
                "  enabled BOOLEAN NOT NULL DEFAULT TRUE,"
                "  last_seen TIMESTAMP"
                ")"
            )
        )
        for key, value in settings.items():
            conn.execute(
                text("INSERT INTO settings (key, value, category) VALUES (:k, :v, 'livelink')"),
                {"k": key, "v": value},
            )
        for n, row in enumerate(devices or []):
            conn.execute(
                text(
                    "INSERT INTO livelink_devices (device_id, kind, vin, enabled, last_seen) "
                    "VALUES (:id, :kind, :vin, :enabled, :seen)"
                ),
                {"id": f"dev_{n}", **row},
            )
    return engine


def _enabled(engine) -> str | None:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT value FROM settings WHERE key = 'livelink_enabled'")
        ).scalar_one_or_none()


MQTT_ON = {
    "livelink_enabled": "false",
    "livelink_mqtt_enabled": "true",
    "livelink_mqtt_broker_host": "10.10.1.11",
}
REPORTED = {"vin": "1HGCM82633A004352", "enabled": True, "seen": datetime(2026, 9, 1, 12, 0)}
WICAN = {**REPORTED, "kind": "wican"}
UPLOADED = {**REPORTED, "kind": "torque"}


def test_is_fatal():
    """Skipped, a working install's MQTT or Torque data silently stops."""
    assert _load().FATAL is True


def test_enables_an_install_receiving_mqtt(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _engine(engine, MQTT_ON, [WICAN])

    _load().upgrade(engine)

    assert _enabled(engine) == "true"


def test_enables_an_install_whose_torque_source_has_uploaded(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _engine(engine, {"livelink_enabled": "false"}, [UPLOADED])

    _load().upgrade(engine)

    assert _enabled(engine) == "true"


def test_enables_when_the_setting_row_is_absent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    settings = {k: v for k, v in MQTT_ON.items() if k != "livelink_enabled"}
    _engine(engine, settings, [WICAN])

    _load().upgrade(engine)

    assert _enabled(engine) == "true"


def test_leaves_a_fresh_install_off(engine_for_migration):
    """Migration 034 seeds 'false' and nothing else is configured."""
    _dialect, engine, _url = engine_for_migration
    _engine(
        engine,
        {
            "livelink_enabled": "false",
            "livelink_mqtt_enabled": "false",
            "livelink_mqtt_broker_host": "",
        },
    )

    _load().upgrade(engine)

    assert _enabled(engine) == "false"


def test_mqtt_on_with_no_broker_is_not_evidence(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _engine(engine, {**MQTT_ON, "livelink_mqtt_broker_host": ""}, [WICAN])

    _load().upgrade(engine)

    assert _enabled(engine) == "false"


def test_mqtt_configured_but_no_device_ever_reported_is_not_evidence(engine_for_migration):
    """Configuration alone is not data flowing: the same bar the Torque branch has."""
    _dialect, engine, _url = engine_for_migration
    _engine(engine, MQTT_ON, [{**WICAN, "seen": None}])

    _load().upgrade(engine)

    assert _enabled(engine) == "false"


def test_a_capitalised_true_counts_as_off_as_the_app_reads_it(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _engine(engine, {**MQTT_ON, "livelink_enabled": "True"}, [WICAN])

    _load().upgrade(engine)

    assert _enabled(engine) == "true"


def test_a_dormant_torque_source_is_not_evidence(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _engine(
        engine,
        {"livelink_enabled": "false"},
        [
            {**UPLOADED, "seen": None},  # never uploaded
            {**UPLOADED, "vin": None},  # unlinked: the route stored nothing
            {**UPLOADED, "enabled": False},  # switched off
        ],
    )

    _load().upgrade(engine)

    assert _enabled(engine) == "false"


def test_leaves_an_enabled_install_alone_and_is_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _engine(engine, {**MQTT_ON, "livelink_enabled": "true"}, [WICAN])
    migration = _load()

    migration.upgrade(engine)
    migration.upgrade(engine)

    assert _enabled(engine) == "true"
    with engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT COUNT(*) FROM settings WHERE key = 'livelink_enabled'")
            ).scalar()
            == 1
        )


def test_missing_tables_are_a_no_op(tmp_path):
    _load().upgrade(create_engine(f"sqlite:///{tmp_path / 'empty.db'}"))

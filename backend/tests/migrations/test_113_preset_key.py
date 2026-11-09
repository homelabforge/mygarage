"""Migration 113: preset_key column, plus the two backfills it owes."""

import importlib.util
from pathlib import Path

from sqlalchemy import inspect, text

_MIG = (
    Path(__file__).resolve().parents[2] / "app" / "migrations" / "113_livelink_device_preset_key.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("mig113", _MIG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _schema(engine):
    """The three tables the migration touches, at their pre-113 shape."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE livelink_devices ("
                "  device_id VARCHAR(20) PRIMARY KEY,"
                "  label VARCHAR(100),"
                "  kind VARCHAR(20) NOT NULL DEFAULT 'wican'"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE livelink_topic_maps ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  device_id VARCHAR(20) NOT NULL,"
                "  topic VARCHAR(255) NOT NULL,"
                "  role VARCHAR(12) NOT NULL DEFAULT 'telemetry',"
                "  param_key VARCHAR(100),"
                "  unit VARCHAR(20),"
                "  param_class VARCHAR(50)"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE livelink_parameters ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  param_key VARCHAR(100) NOT NULL UNIQUE,"
                "  display_name VARCHAR(100),"
                "  unit VARCHAR(20),"
                "  param_class VARCHAR(50),"
                "  category VARCHAR(50),"
                "  show_on_dashboard BOOLEAN NOT NULL DEFAULT TRUE,"
                "  archive_only BOOLEAN NOT NULL DEFAULT FALSE,"
                "  storage_interval_seconds INTEGER NOT NULL DEFAULT 0"
                ")"
            )
        )


def test_migration_is_fatal():
    """An add-column migration that is not FATAL boots the app against a
    column the ORM SELECTs and the database does not have."""
    assert _load().FATAL is True


def test_adds_the_column(tmp_path, sync_engine):
    engine = sync_engine(f"sqlite:///{tmp_path / 'm.db'}")
    _schema(engine)

    _load().upgrade(engine)

    columns = {c["name"] for c in inspect(engine).get_columns("livelink_devices")}
    assert "preset_key" in columns


def test_is_idempotent(tmp_path, sync_engine):
    engine = sync_engine(f"sqlite:///{tmp_path / 'm.db'}")
    _schema(engine)
    module = _load()

    module.upgrade(engine)
    module.upgrade(engine)  # must not raise

    columns = {c["name"] for c in inspect(engine).get_columns("livelink_devices")}
    assert "preset_key" in columns


def test_backfills_preset_key_by_title(tmp_path, sync_engine):
    """The one device that already has a preset predates the column."""
    engine = sync_engine(f"sqlite:///{tmp_path / 'm.db'}")
    _schema(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO livelink_devices (device_id, label, kind) "
                "VALUES ('rvgw', 'Mopeka propane (2 tanks)', 'generic_mqtt')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO livelink_devices (device_id, label, kind) "
                "VALUES ('hand1', 'My own gateway', 'generic_mqtt')"
            )
        )

    _load().upgrade(engine)

    with engine.begin() as conn:
        rows = dict(conn.execute(text("SELECT device_id, preset_key FROM livelink_devices")).all())
    assert rows["rvgw"] == "mopeka_two_tank"
    assert rows["hand1"] is None


def test_backfills_parameters_for_existing_mappings(tmp_path, sync_engine):
    """A mapping created before this change has no parameter row, so the
    sidecar's show-on-dashboard switch would PUT into a 404."""
    engine = sync_engine(f"sqlite:///{tmp_path / 'm.db'}")
    _schema(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO livelink_topic_maps (device_id, topic, role, param_key, unit, param_class) "
                "VALUES ('hand1', 'x/y/volts', 'telemetry', 'AUX_VOLTS', 'V', 'voltage')"
            )
        )
        # A status row carries no param_key and must not produce a parameter.
        conn.execute(
            text(
                "INSERT INTO livelink_topic_maps (device_id, topic, role, param_key) "
                "VALUES ('hand1', 'x/y/status', 'status', NULL)"
            )
        )

    _load().upgrade(engine)

    with engine.begin() as conn:
        keys = [r[0] for r in conn.execute(text("SELECT param_key FROM livelink_parameters")).all()]
    assert keys == ["AUX_VOLTS"]


def test_backfill_parameters_dedupes_shared_param_key_across_topics(tmp_path, sync_engine):
    """Two mappings can share one param_key under different topics
    (livelink_topic_maps is only UNIQUE(topic, param_key)), but
    livelink_parameters.param_key is globally unique. A backfill that
    groups by the (param_key, unit, param_class) triple instead of by
    param_key alone would try to INSERT the same key twice and crash --
    and since this migration is FATAL=True, that takes the whole app
    down with it."""
    engine = sync_engine(f"sqlite:///{tmp_path / 'm.db'}")
    _schema(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO livelink_topic_maps (device_id, topic, role, param_key, unit, param_class) "
                "VALUES ('hand1', 'x/y/volts', 'telemetry', 'AUX_VOLTS', 'V', 'voltage')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO livelink_topic_maps (device_id, topic, role, param_key, unit, param_class) "
                "VALUES ('hand1', 'x/z/volts', 'telemetry', 'AUX_VOLTS', 'mV', 'voltage')"
            )
        )

    _load().upgrade(engine)  # must not raise IntegrityError

    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT param_key FROM livelink_parameters WHERE param_key = 'AUX_VOLTS'")
        ).all()
    assert len(rows) == 1


def test_backfill_does_not_duplicate_an_existing_parameter(tmp_path, sync_engine):
    engine = sync_engine(f"sqlite:///{tmp_path / 'm.db'}")
    _schema(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO livelink_topic_maps (device_id, topic, role, param_key, unit, param_class) "
                "VALUES ('hand1', 'x/y/volts', 'telemetry', 'AUX_VOLTS', 'V', 'voltage')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO livelink_parameters (param_key, display_name, show_on_dashboard, archive_only) "
                "VALUES ('AUX_VOLTS', 'Hand Tuned Name', 1, 0)"
            )
        )

    _load().upgrade(engine)

    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT display_name FROM livelink_parameters WHERE param_key = 'AUX_VOLTS'")
        ).all()
    assert len(rows) == 1
    assert rows[0][0] == "Hand Tuned Name"

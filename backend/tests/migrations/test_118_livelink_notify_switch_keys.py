"""Migration 118: LiveLink notification switches move to the keys Settings writes.

The dispatcher read `notify_livelink_*`, which no screen wrote; it now reads
`livelink_notify_*`. An old key switched off must stay off.
"""

from sqlalchemy import inspect, text

from tests.migrations._loader import load_migration


def _load():
    return load_migration("118_livelink_notify_switch_keys", "mig118")


def _settings(engine, rows: dict[str, str | None]) -> None:
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
        for key, value in rows.items():
            conn.execute(
                text("INSERT INTO settings (key, value, category) VALUES (:k, :v, 'livelink')"),
                {"k": key, "v": value},
            )


def _value(engine, key: str) -> str | None:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT value FROM settings WHERE key = :k"), {"k": key}
        ).scalar_one_or_none()


def test_is_not_fatal():
    """Skipped, an event silenced only through the old key speaks again: nothing fails."""
    assert _load().FATAL is False


def test_an_old_switch_that_was_off_stays_off(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _settings(engine, {"notify_livelink_threshold_alerts": "false"})

    _load().upgrade(engine)

    assert _value(engine, "livelink_notify_threshold_alerts") == "false"


def test_an_empty_new_key_counts_as_unset(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _settings(
        engine,
        {"notify_livelink_device_offline": "false", "livelink_notify_device_offline": ""},
    )

    _load().upgrade(engine)

    assert _value(engine, "livelink_notify_device_offline") == "false"


def test_the_switch_in_settings_wins(engine_for_migration):
    """Set through the screen, it is what someone chose."""
    _dialect, engine, _url = engine_for_migration
    _settings(
        engine,
        {
            "notify_livelink_firmware_update": "false",
            "livelink_notify_firmware_update": "true",
        },
    )

    _load().upgrade(engine)

    assert _value(engine, "livelink_notify_firmware_update") == "true"


def test_an_old_switch_left_on_writes_nothing(engine_for_migration):
    """Migration 034 seeded them all 'true': on, the new key's default already agrees."""
    _dialect, engine, _url = engine_for_migration
    _settings(engine, {"notify_livelink_new_device": "true"})

    _load().upgrade(engine)

    assert _value(engine, "livelink_notify_new_device") is None


def test_is_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _settings(engine, {"notify_livelink_threshold_alerts": "0"})
    module = _load()

    module.upgrade(engine)
    module.upgrade(engine)

    assert _value(engine, "livelink_notify_threshold_alerts") == "false"


def test_skips_a_database_without_settings(engine_for_migration):
    _dialect, engine, _url = engine_for_migration

    _load().upgrade(engine)  # must not raise

    assert not inspect(engine).has_table("settings")

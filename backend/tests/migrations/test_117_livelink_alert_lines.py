"""Migration 117: a critical line and a notify-once state on each parameter,
and the default tank and battery lines for Mopeka sensors added before them."""

from sqlalchemy import inspect, text

from tests.migrations._loader import load_migration


def _load():
    return load_migration("117_livelink_alert_lines", "mig117")


def _schema(engine, rows: list[tuple[str, float | None]] | None = None) -> None:
    """livelink_parameters at its pre-117 shape, with (param_key, warning_min) rows."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE livelink_parameters ("
                "  id INTEGER PRIMARY KEY,"
                "  param_key VARCHAR(100) NOT NULL UNIQUE,"
                "  unit VARCHAR(20),"
                "  warning_min FLOAT,"
                "  warning_max FLOAT"
                ")"
            )
        )
        for n, (key, warning_min) in enumerate(rows or [], start=1):
            conn.execute(
                text(
                    "INSERT INTO livelink_parameters (id, param_key, unit, warning_min) "
                    "VALUES (:id, :key, '%', :low)"
                ),
                {"id": n, "key": key, "low": warning_min},
            )


def _lines(engine) -> dict[str, tuple[float | None, float | None]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT param_key, warning_min, critical_min FROM livelink_parameters")
        ).all()
    return {key: (low, critical) for key, low, critical in rows}


def test_is_fatal():
    """The ORM selects both columns: skipped, every parameter read fails."""
    assert _load().FATAL is True


def test_adds_the_columns(engine_for_migration):
    dialect, engine, _url = engine_for_migration
    _schema(engine)

    _load().upgrade(engine)

    types = {
        c["name"]: str(c["type"]).upper()
        for c in inspect(engine).get_columns("livelink_parameters")
    }
    assert {"critical_min", "alert_state", "alert_retry_at"} <= types.keys()
    # DATETIME is not a PostgreSQL type: each dialect gets its own spelling.
    assert types["alert_retry_at"].startswith("TIMESTAMP" if dialect == "pg" else "DATETIME")


def test_is_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _schema(engine, [("PROPANE_T1_LEVEL_PCT", None)])
    module = _load()

    module.upgrade(engine)
    module.upgrade(engine)

    assert _lines(engine)["PROPANE_T1_LEVEL_PCT"] == (25.0, 10.0)


def test_gives_existing_tanks_and_batteries_their_default_lines(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _schema(
        engine,
        [
            ("PROPANE_T1_LEVEL_PCT", None),
            ("PROPANE_T12_LEVEL_PCT", None),
            ("PROPANE_T1_SENSOR_BATT_PCT", None),
            ("PROPANE_T1_TEMP_C", None),
        ],
    )

    _load().upgrade(engine)

    lines = _lines(engine)
    assert lines["PROPANE_T1_LEVEL_PCT"] == (25.0, 10.0)
    assert lines["PROPANE_T12_LEVEL_PCT"] == (25.0, 10.0)
    assert lines["PROPANE_T1_SENSOR_BATT_PCT"] == (20.0, None)
    assert lines["PROPANE_T1_TEMP_C"] == (None, None)


def test_keeps_a_line_someone_already_set(engine_for_migration):
    """Through the API, before the settings had a field for it."""
    _dialect, engine, _url = engine_for_migration
    _schema(engine, [("PROPANE_T1_LEVEL_PCT", 40.0), ("PROPANE_T1_SENSOR_BATT_PCT", 15.0)])

    _load().upgrade(engine)

    lines = _lines(engine)
    assert lines["PROPANE_T1_LEVEL_PCT"] == (40.0, None)
    assert lines["PROPANE_T1_SENSOR_BATT_PCT"] == (15.0, None)


def test_leaves_keys_that_only_look_alike(engine_for_migration):
    """Not the preset's shape: no sensor index, or something after the suffix."""
    _dialect, engine, _url = engine_for_migration
    _schema(
        engine,
        [
            ("PROPANE_TX_LEVEL_PCT", None),
            ("PROPANE_T1_LEVEL_PCT_RAW", None),
            ("RV_PROPANE_T1_LEVEL_PCT", None),
            ("FUEL_LEVEL_PCT", None),
        ],
    )

    _load().upgrade(engine)

    assert set(_lines(engine).values()) == {(None, None)}


def test_skips_a_database_without_the_table(engine_for_migration):
    _dialect, engine, _url = engine_for_migration

    _load().upgrade(engine)

    assert not inspect(engine).has_table("livelink_parameters")

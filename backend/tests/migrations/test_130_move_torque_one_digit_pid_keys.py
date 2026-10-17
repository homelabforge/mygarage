"""Migration 130: Torque's one-digit PID keys move onto their padded keys (#223)."""

import json
import logging
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

import app.migrations as _m
from app.migrations.runner import MigrationRunner

_NAME = "130_move_torque_one_digit_pid_keys"
T1, T2, T3 = "2026-10-01 10:00:00", "2026-10-01 10:00:05", "2026-10-01 10:00:10"
DAY = "2026-10-01 00:00:00"
#: Summarised whole, then pruned down to three readings: the cutoff day.
P1, P2 = "2026-07-01 08:00:00", "2026-07-01 08:00:05"
PDAY = "2026-07-01 00:00:00"
#: Past retention: summaries only.
OLD = "2026-06-01 00:00:00"
#: Summarised before a late reading landed (S2): the summary is short of raw.
S1, S2 = "2026-08-01 09:00:00", "2026-08-01 09:30:00"
SDAY = "2026-08-01 00:00:00"
#: A duplicate on a day the new key has no summary for.
N1, N2 = "2026-08-15 09:00:00", "2026-08-15 09:05:00"
NDAY = "2026-08-15 00:00:00"
#: Pruned to one reading, plus a duplicate that came in days later, after the
#: summary was built, so the summary never counted it (Codex R1-H2).
L1, L2 = "2026-09-01 09:00:00", "2026-09-01 09:10:00"
LATE = "2026-09-03 12:00:00"
LDAY = "2026-09-01 00:00:00"
_TQ = "tq_0000a130"  # a Torque source on V1
_GONE = "tq_0000dead"  # a deleted one: only its trip is left, on V2
_WICAN = "aabbccdd0130"  # a WiCAN on V1 that happens to send a key named KC
V1, V2, V3 = "VIN130TORQUE00001", "VIN130TORQUE00002", "VIN130WICAN000003"


def _load():
    """Through MigrationRunner._load_module, the runner's own path (no sys.modules entry)."""
    path = Path(_m.__file__).parent / f"{_NAME}.py"
    return MigrationRunner("sqlite://", path.parent)._load_module(_NAME, path)


def _make_tables(engine) -> None:
    is_pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts = "TIMESTAMP" if is_pg else "DATETIME"
    num = "DOUBLE PRECISION" if is_pg else "REAL"
    with engine.begin() as conn:
        for ddl in (
            f"CREATE TABLE livelink_devices (id {pk}, device_id VARCHAR(20) NOT NULL UNIQUE, "
            "vin VARCHAR(17), kind VARCHAR(20) NOT NULL, odometer_param_key VARCHAR(100))",
            f"CREATE TABLE drive_sessions (id {pk}, vin VARCHAR(17) NOT NULL, "
            f"device_id VARCHAR(20) NOT NULL, started_at {ts} NOT NULL, ended_at {ts})",
            f"CREATE TABLE vehicle_telemetry (id {pk}, vin VARCHAR(17) NOT NULL, "
            f"device_id VARCHAR(20) NOT NULL, param_key VARCHAR(100) NOT NULL, value {num} NOT NULL, "
            f"timestamp {ts} NOT NULL, received_at {ts} NOT NULL, UNIQUE (device_id, param_key, timestamp))",
            f"CREATE TABLE vehicle_telemetry_latest (id {pk}, vin VARCHAR(17) NOT NULL, "
            f"param_key VARCHAR(100) NOT NULL, value {num} NOT NULL, timestamp {ts} NOT NULL, "
            f"received_at {ts} NOT NULL, UNIQUE (vin, param_key))",
            f"CREATE TABLE telemetry_daily_summary (id {pk}, vin VARCHAR(17) NOT NULL, "
            f"param_key VARCHAR(100) NOT NULL, date {ts} NOT NULL, min_value {num}, max_value {num}, "
            f"avg_value {num}, sample_count INTEGER NOT NULL DEFAULT 0, UNIQUE (vin, param_key, date))",
            "CREATE TABLE vehicles (vin VARCHAR(17) PRIMARY KEY)",
            f"CREATE TABLE livelink_topic_maps (id {pk}, device_id VARCHAR(20) NOT NULL, param_key VARCHAR(100))",
            "CREATE TABLE settings (key VARCHAR(50) PRIMARY KEY, value TEXT, "
            "category VARCHAR(50) NOT NULL DEFAULT 'general', description TEXT, "
            "encrypted BOOLEAN NOT NULL DEFAULT FALSE)",
            f"CREATE TABLE livelink_parameters (id {pk}, param_key VARCHAR(100) NOT NULL UNIQUE, "
            "display_name VARCHAR(100), unit VARCHAR(20), param_class VARCHAR(50), category VARCHAR(50), "
            f"icon VARCHAR(50), warning_min {num}, warning_max {num}, critical_min {num}, "
            f"warning_last_notified_at {ts}, alert_state VARCHAR(10), alert_retry_at {ts}, "
            "display_order INTEGER NOT NULL DEFAULT 0, show_on_dashboard BOOLEAN NOT NULL DEFAULT TRUE, "
            "archive_only BOOLEAN NOT NULL DEFAULT FALSE, storage_interval_seconds INTEGER NOT NULL DEFAULT 0, "
            f"created_at {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at {ts})",
        ):
            conn.execute(text(ddl))


def _rows(conn, table: str, cols: tuple[str, ...], rows: list[tuple]) -> None:
    names, marks = ", ".join(cols), ", ".join(f":{c}" for c in cols)
    for row in rows:
        conn.execute(
            text(f"INSERT INTO {table} ({names}) VALUES ({marks})"),
            dict(zip(cols, row, strict=True)),
        )


def _seed(engine) -> None:
    with engine.begin() as conn:
        _rows(
            conn,
            "livelink_devices",
            ("device_id", "vin", "kind", "odometer_param_key"),
            [
                (_TQ, V1, "torque", "KA"),
                (_WICAN, V1, "wican", "KA"),
                ("aabbccdd0003", V3, "wican", None),
            ],
        )
        _rows(
            conn,
            "drive_sessions",
            ("vin", "device_id", "started_at", "ended_at"),
            [
                (V1, _TQ, T1, T3),  # 1: KC, KD in its window
                (V2, _GONE, T1, T3),  # 2: K5 in its window
                (V1, _TQ, T1, None),  # 3: still open
                (V1, _WICAN, T1, T3),  # 4: not a Torque source
                (V1, _TQ, "2026-10-02 10:00:00", "2026-10-02 11:00:00"),  # 5: nothing in its window
            ],
        )
        _rows(conn, "vehicles", ("vin",), [(V1,), (V2,), (V3,)])
        _rows(
            conn,
            "livelink_topic_maps",
            ("device_id", "param_key"),
            [
                ("aabbccdd0003", "KE"),
                ("aabbccdd0003", "K7"),
            ],
        )
        _rows(
            conn,
            "livelink_parameters",
            (
                "param_key",
                "display_name",
                "unit",
                "category",
                "icon",
                "warning_max",
                "show_on_dashboard",
                "archive_only",
            ),
            [
                ("KC", "Kc", None, "other", None, 6000.0, False, False),
                ("KD", "Road speed", None, "drivetrain", "gauge", 130.0, True, False),
                ("SPEED", "Speed", None, "engine", None, None, True, False),
                # Set by hand, but COOLANT_TMP has its own of each, so none of it lands.
                ("K5", "Coolant", None, "temperature", "thermometer", 120.0, True, False),
                ("COOLANT_TMP", "Engine temp", "degC", "engine", "coolant", 110.0, True, False),
                ("K3", "K3", None, "other", None, None, True, True),
                ("KE", "Ke", None, "other", None, None, True, False),
                ("K7", "Tank 7", None, "other", None, None, True, False),
                # Each kept by one thing only: V3's latest, V3's summary, V3's
                # raw reading, the WiCAN's odometer key.
                ("K4", "K4", None, "other", None, None, True, False),
                ("K6", "K6", None, "other", None, None, True, False),
                ("K8", "K8", None, "other", None, None, True, False),
                ("KA", "Ka", None, "other", None, None, True, False),
                # An empty unit counts as none, as auto_register_parameter has it.
                ("INTAKE_PRESSURE", "Intake Pressure", "", "other", None, None, True, False),
            ],
        )
        _rows(
            conn,
            "vehicle_telemetry",
            ("vin", "device_id", "param_key", "value", "timestamp", "received_at"),
            [
                (V1, _TQ, "KC", 2549.0, T1, T1),
                (V1, _TQ, "KC", 2600.0, T2, T2),  # the ENGINE_RPM reading at T2, another value
                (V1, _TQ, "ENGINE_RPM", 2550.0, T2, T2),
                (V1, _TQ, "KD", 48.0, T1, T1),
                (V1, _TQ, "KD", 50.0, T2, T2),  # the same reading is on file under SPEED
                (V1, _TQ, "SPEED", 50.0, T2, T2),
                (V1, _TQ, "K3", 2.0, T1, T1),
                (V1, _TQ, "KE", 10.0, T1, T1),
                (V1, _TQ, "THROTTLE", 16.5, T1, T1),
                (V1, _TQ, "KD", 40.0, P1, P1),  # what pruning left of 2026-07-01
                (V1, _TQ, "KD", 95.0, P2, P2),
                (V1, _TQ, "SPEED", 95.0, P2, P2),
                (V1, _TQ, "KD", 20.0, S1, S1),  # the SPEED reading at S1
                (V1, _TQ, "SPEED", 20.0, S1, S1),
                (V1, _TQ, "KD", 60.0, S2, S2),  # landed after 2026-08-01 was summarised
                (V1, _TQ, "KD", 70.0, N1, N1),  # the SPEED reading at N1
                (V1, _TQ, "SPEED", 70.0, N1, N1),
                (V1, _TQ, "KD", 80.0, N2, N2),
                (V1, _TQ, "KD", 50.0, L1, L1),  # what pruning left of 2026-09-01
                (V1, _TQ, "KD", 100.0, L2, LATE),  # the SPEED reading at L2, both days late
                (V1, _TQ, "SPEED", 100.0, L2, LATE),
                (V2, _GONE, "K5", 69.0, T1, T1),
                (V1, _WICAN, "KC", 900.0, T1, T1),
                # Today's, so not summarised yet.
                (V3, "aabbccdd0003", "K8", 8.0, "2026-10-02 09:00:00", "2026-10-02 09:00:00"),
            ],
        )
        _rows(
            conn,
            "vehicle_telemetry_latest",
            ("vin", "param_key", "value", "timestamp", "received_at"),
            [
                (V1, "KC", 2549.0, T1, T1),
                (V1, "KD", 48.0, T1, T1),
                (V1, "SPEED", 51.0, T3, T3),
                (V1, "K5", 70.0, T3, T3),
                (V1, "COOLANT_TMP", 60.0, T1, T1),
                (V3, "KC", 900.0, T1, T1),
                (V1, "K4", 30.0, T1, T1),
                (V1, "K6", 6.0, T1, T1),
                (V1, "K8", 8.0, T1, T1),
                (V3, "K4", 31.0, T1, T1),
                (V1, "KB", 101.0, T1, T1),  # moves KB, so INTAKE_PRESSURE gets its unit
            ],
        )
        # DAY's summaries are what generate_daily_summary makes of the raw rows
        # above (per vehicle, key and day, every device), so a test can't pass
        # on summaries the raw rows contradict (codex-plan/R1-H1).
        _rows(
            conn,
            "telemetry_daily_summary",
            ("vin", "param_key", "date", "min_value", "max_value", "avg_value", "sample_count"),
            [
                (V1, "KC", DAY, 900.0, 2600.0, (2549.0 + 2600.0 + 900.0) / 3, 3),
                (V1, "ENGINE_RPM", DAY, 2550.0, 2550.0, 2550.0, 1),
                (V1, "KD", DAY, 48.0, 50.0, 49.0, 2),
                (V1, "SPEED", DAY, 50.0, 50.0, 50.0, 1),
                (V1, "K3", DAY, 2.0, 2.0, 2.0, 1),
                (V1, "KE", DAY, 10.0, 10.0, 10.0, 1),
                (V1, "THROTTLE", DAY, 16.5, 16.5, 16.5, 1),
                (V2, "K5", DAY, 69.0, 69.0, 69.0, 1),
                # Ten KD readings summarised; pruning has since left two, and one duplicate.
                (V1, "KD", PDAY, 30.0, 95.0, 60.0, 10),
                (V1, "SPEED", PDAY, 95.0, 95.0, 95.0, 1),
                # Built before KD's 60 landed: one reading each.
                (V1, "KD", SDAY, 20.0, 20.0, 20.0, 1),
                (V1, "SPEED", SDAY, 20.0, 20.0, 20.0, 1),
                # KD only: no SPEED summary that day.
                (V1, "KD", NDAY, 70.0, 80.0, 75.0, 2),
                # Ten KD readings at 50, built before the late 100 came in; no SPEED row.
                (V1, "KD", LDAY, 50.0, 50.0, 50.0, 10),
                (V1, "KD", OLD, 40.0, 100.0, 70.0, 3),
                (V1, "SPEED", OLD, 10.0, 90.0, 50.0, 1),
                (V1, "KF", OLD, None, None, None, 0),
                (V1, "INTAKE_TEMP", OLD, 18.0, 25.0, 20.0, 4),
                (V3, "KC", DAY, 900.0, 900.0, 900.0, 1),
                (V3, "K6", OLD, 6.0, 6.0, 6.0, 1),
            ],
        )


def _f(value):
    return None if value is None else float(value)


def _telemetry(engine) -> list[tuple]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT device_id, param_key, value FROM vehicle_telemetry")).all()
    return sorted((d, k, float(v)) for d, k, v in rows)


def _latest(engine) -> dict:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT vin, param_key, value, timestamp FROM vehicle_telemetry_latest")
        ).all()
    return {(vin, k): (float(v), str(ts)[:19]) for vin, k, v, ts in rows}


def _summaries(engine) -> dict:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT vin, param_key, date, min_value, max_value, avg_value, sample_count "
                "FROM telemetry_daily_summary"
            )
        ).all()
    return {
        (vin, k, str(day)[:10]): (_f(mn), _f(mx), _f(av), n) for vin, k, day, mn, mx, av, n in rows
    }


def _odometer_keys(engine) -> dict:
    with engine.connect() as conn:
        return dict(
            conn.execute(text("SELECT device_id, odometer_param_key FROM livelink_devices")).all()
        )


_REGISTRY = (
    "display_name",
    "unit",
    "param_class",
    "category",
    "icon",
    "warning_min",
    "critical_min",
    "warning_max",
    "show_on_dashboard",
    "archive_only",
)


def _registry(engine) -> dict:
    with engine.connect() as conn:
        rows = conn.execute(
            text(f"SELECT param_key, {', '.join(_REGISTRY)} FROM livelink_parameters")
        ).all()
    return {r[0]: (*r[1:6], *(_f(v) for v in r[6:9]), bool(r[9]), bool(r[10])) for r in rows}


def _listed(engine):
    with engine.connect() as conn:
        value = conn.execute(
            text("SELECT value FROM settings WHERE key = 'torque_session_repair'")
        ).scalar()
    return None if value is None else json.loads(value)


def _migrated(engine):
    _make_tables(engine)
    _seed(engine)
    _load().upgrade(engine)
    return engine


def test_130_is_not_fatal():
    """D12: a data move must never stop the migrations behind it."""
    assert _load().FATAL is False


def test_130_moves_each_key_where_the_parser_files_it_now():
    """Frozen in the migration, so a later map change needs a migration of its own."""
    from app.services.torque_pid_map import parse_torque_query

    moves = _load()._MOVES
    assert set(moves) == {f"K{d}" for d in "0123456789ABCDEF"}
    assert moves == {raw: next(iter(parse_torque_query({raw.lower(): "1"}).obd)) for raw in moves}


def test_130_moves_raw_telemetry_for_torque_sources_only(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    assert _telemetry(_migrated(engine)) == sorted(
        [
            (_TQ, "ENGINE_RPM", 2549.0),
            (_TQ, "ENGINE_RPM", 2550.0),  # KC's 2600 at T2 was the duplicate
            (_TQ, "SPEED", 48.0),
            (_TQ, "SPEED", 50.0),
            (_TQ, "K03", 2.0),
            (_TQ, "TIMING_ADVANCE", 10.0),
            (_TQ, "THROTTLE", 16.5),
            (_TQ, "SPEED", 40.0),
            (_TQ, "SPEED", 95.0),
            (_TQ, "SPEED", 20.0),  # KD's 20 at S1 was the duplicate
            (_TQ, "SPEED", 60.0),
            (_TQ, "SPEED", 70.0),  # KD's 70 at N1 was the duplicate
            (_TQ, "SPEED", 80.0),
            (_TQ, "SPEED", 50.0),
            (_TQ, "SPEED", 100.0),  # KD's late 100 at L2 was the duplicate
            (_GONE, "COOLANT_TMP", 69.0),
            (_WICAN, "KC", 900.0),
            ("aabbccdd0003", "K8", 8.0),
        ]
    )


def test_130_keeps_the_newer_latest_value(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    assert _latest(_migrated(engine)) == {
        (V1, "ENGINE_RPM"): (2549.0, T1),
        (V1, "SPEED"): (51.0, T3),
        (V1, "COOLANT_TMP"): (70.0, T3),
        (V3, "KC"): (900.0, T1),
        (V1, "ENGINE_LOAD"): (30.0, T1),
        (V1, "K06"): (6.0, T1),
        (V1, "K08"): (8.0, T1),
        (V3, "K4"): (31.0, T1),
        (V1, "INTAKE_PRESSURE"): (101.0, T1),
    }


def test_130_summaries_follow_the_raw_duplicates(engine_for_migration, caplog):
    """D10: a day with duplicates whose raw holds at least what its summaries
    counted is rebuilt from the readings that survive, a stale one included;
    one whose raw was pruned loses the duplicates received that day from its
    count and mean and keeps its min and max, logged; a day with no raw merges
    as 059."""
    _dialect, engine, _url = engine_for_migration
    with caplog.at_level(logging.WARNING):
        summaries = _summaries(_migrated(engine))
    assert summaries == {
        # Rebuilt: ENGINE_RPM 2549 and 2550 survive. KC's day goes with the move.
        (V1, "ENGINE_RPM", "2026-10-01"): (2549.0, 2550.0, 2549.5, 2),
        # KD 48 and 50 plus SPEED 50 at the same moment: two readings, not three.
        (V1, "SPEED", "2026-10-01"): (48.0, 50.0, 49.0, 2),
        (V1, "K03", "2026-10-01"): (2.0, 2.0, 2.0, 1),
        (V1, "TIMING_ADVANCE", "2026-10-01"): (10.0, 10.0, 10.0, 1),
        (V1, "THROTTLE", "2026-10-01"): (16.5, 16.5, 16.5, 1),
        (V2, "COOLANT_TMP", "2026-10-01"): (69.0, 69.0, 69.0, 1),
        # Ten summarised, one duplicate: (600 - 95 + 95) / (10 - 1 + 1); min and max kept.
        (V1, "SPEED", "2026-07-01"): (30.0, 95.0, 60.0, 10),
        # Stale but whole: rebuilt from raw, the late 60 included.
        (V1, "SPEED", "2026-08-01"): (20.0, 60.0, 40.0, 2),
        # No SPEED row to merge into: KD's row is renamed and rebuilt.
        (V1, "SPEED", "2026-08-15"): (70.0, 80.0, 75.0, 2),
        # Pruned, and its one duplicate came in after the summary was built, so
        # it was never counted and nothing comes off.
        (V1, "SPEED", "2026-09-01"): (50.0, 50.0, 50.0, 10),
        # Past retention: (210 + 50) / 4.
        (V1, "SPEED", "2026-06-01"): (10.0, 100.0, 65.0, 4),
        (V1, "INTAKE_TEMP", "2026-06-01"): (18.0, 25.0, 20.0, 4),
        (V3, "KC", "2026-10-01"): (900.0, 900.0, 900.0, 1),
        (V3, "K6", "2026-06-01"): (6.0, 6.0, 6.0, 1),
    }
    assert sorted(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING) == [
        f"130: kept min and max for SPEED on {day} (VIN130TO): raw no longer holds the whole day, "
        "so only duplicates received that day came off the count"
        for day in ("2026-07-01", "2026-09-01")
    ]


def test_130_moves_a_torque_devices_odometer_key(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    assert _odometer_keys(_migrated(engine)) == {_TQ: "K0A", _WICAN: "KA", "aabbccdd0003": None}


def test_130_is_idempotent(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    once = _telemetry(_migrated(engine)), _latest(engine), _summaries(engine)
    _load().upgrade(engine)
    assert (_telemetry(engine), _latest(engine), _summaries(engine)) == once


@pytest.mark.parametrize(
    "error",
    [
        OperationalError("UPDATE telemetry_daily_summary", {}, Exception("boom")),
        # What SQLite's DateTime result processor raises on an oddly formatted date.
        ValueError("Couldn't parse datetime string: '01/10/2026 10:00'"),
    ],
    ids=["sqlalchemy", "value"],
)
def test_130_a_failure_moves_nothing_and_does_not_raise(
    engine_for_migration, monkeypatch, caplog, error
):
    """One transaction with no DDL, so the raw moves roll back with the failed step.
    Not only a database error: anything 125 swallows (D12)."""
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    _seed(engine)
    before = _telemetry(engine), _latest(engine)
    mod = _load()

    def _boom(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(mod, "_move_summaries", _boom)
    with caplog.at_level(logging.ERROR):
        mod.upgrade(engine)
    assert (_telemetry(engine), _latest(engine)) == before
    assert any(
        r.levelno == logging.ERROR and r.getMessage().startswith("130:") for r in caplog.records
    )


def test_130_without_a_torque_source_changes_nothing(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    with engine.begin() as conn:
        _rows(conn, "livelink_devices", ("device_id", "vin", "kind"), [(_WICAN, V1, "wican")])
        _rows(
            conn,
            "vehicle_telemetry",
            ("vin", "device_id", "param_key", "value", "timestamp", "received_at"),
            [(V1, _WICAN, "KC", 900.0, T1, T1)],
        )
    _load().upgrade(engine)
    assert _telemetry(engine) == [(_WICAN, "KC", 900.0)]


def test_130_without_the_tables_does_nothing(engine_for_migration, caplog):
    """A bare database returns before touching the tables, so nothing gets swallowed and logged."""
    _dialect, engine, _url = engine_for_migration
    with caplog.at_level(logging.ERROR):
        _load().upgrade(engine)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_130_carries_what_someone_set_and_drops_raw_rows_nothing_names(
    engine_for_migration, caplog
):
    _dialect, engine, _url = engine_for_migration
    with caplog.at_level(logging.INFO):
        registry = _registry(_migrated(engine))
    assert registry == {
        # Still named by the WiCAN's raw row: kept as it was, alert line and all.
        "KC": ("Kc", None, None, "other", None, None, None, 6000.0, False, False),
        # New: frozen defaults. KC's alert line and hidden switch don't follow.
        "ENGINE_RPM": (
            "Engine Rpm",
            "rpm",
            "frequency",
            "engine",
            None,
            None,
            None,
            None,
            True,
            False,
        ),
        # KD's name, category and icon, onto a row still on its defaults; KD is
        # gone, its line logged.
        "SPEED": ("Road speed", "km/h", None, "drivetrain", "gauge", None, None, None, True, False),
        # Its own name, unit, category, icon and line stay; K5 is gone, its 120 logged.
        "COOLANT_TMP": (
            "Engine temp",
            "degC",
            None,
            "engine",
            "coolant",
            None,
            None,
            110.0,
            True,
            False,
        ),
        "K03": ("K03", None, None, "other", None, None, None, None, True, True),
        # Named by a topic map, so kept; its target is still made.
        "KE": ("Ke", None, None, "other", None, None, None, None, True, False),
        "TIMING_ADVANCE": (
            "Timing Advance",
            "°",
            None,
            "other",
            None,
            None,
            None,
            None,
            True,
            True,
        ),
        # Moved with no raw registry row: the summary's KF.
        "INTAKE_TEMP": (
            "Intake Temp",
            "°C",
            "temperature",
            "temperature",
            None,
            None,
            None,
            None,
            True,
            False,
        ),
        "K0A": ("K0A", None, None, "other", None, None, None, None, True, True),
        # Each still named by one thing (V3's latest, V3's summary, V3's raw
        # reading, the WiCAN's odometer key), so kept; their targets are made.
        "K4": ("K4", None, None, "other", None, None, None, None, True, False),
        "ENGINE_LOAD": ("Engine Load", "%", None, "other", None, None, None, None, True, True),
        "K6": ("K6", None, None, "other", None, None, None, None, True, False),
        "K06": ("K06", None, None, "other", None, None, None, None, True, True),
        "K8": ("K8", None, None, "other", None, None, None, None, True, False),
        "K08": ("K08", None, None, "other", None, None, None, None, True, True),
        "KA": ("Ka", None, None, "other", None, None, None, None, True, False),
        # Nothing of K7 moved: untouched, and no K07.
        "K7": ("Tank 7", None, None, "other", None, None, None, None, True, False),
        # Its empty unit filled from Torque's, as a NULL one would be.
        "INTAKE_PRESSURE": (
            "Intake Pressure",
            "kPa",
            None,
            "other",
            None,
            None,
            None,
            None,
            True,
            False,
        ),
    }
    assert [
        r.getMessage() for r in caplog.records if r.getMessage().startswith("130: dropped")
    ] == [
        "130: dropped the alert lines on K5 (warning_min None, critical_min None, warning_max 120.0): "
        "Torque never sends alerts",
        "130: dropped the alert lines on KD (warning_min None, critical_min None, warning_max 130.0): "
        "Torque never sends alerts",
    ]


def test_130_lists_the_closed_torque_trips_the_move_makes_computable(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    assert _listed(_migrated(engine)) == [1, 2]


def test_130_adds_to_a_list_already_waiting(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _make_tables(engine)
    _seed(engine)
    with engine.begin() as conn:
        _rows(
            conn,
            "settings",
            ("key", "value", "category"),
            [("torque_session_repair", "[99]", "livelink")],
        )
    _load().upgrade(engine)
    assert _listed(engine) == [1, 2, 99]


def test_130_a_second_run_lists_nothing_new(engine_for_migration):
    _dialect, engine, _url = engine_for_migration
    _migrated(engine)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM settings"))
    _load().upgrade(engine)
    assert _listed(engine) is None

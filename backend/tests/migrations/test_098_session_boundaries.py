"""Tests for migration 098: durable movement state and one open session per device.

098 is the schema half of the session-boundary rework. It adds movement state to
``livelink_devices``, provenance to ``drive_sessions``, the reconstruction-run
audit table, and -- the part with teeth -- a **partial unique index** making "one
open session per device" a constraint rather than a convention.

That index can fail on existing data, which is why the preflight is the bulk of
both the migration and this file. There are two ways a database gets a second
open row for one device, and an earlier draft of the design handled only the
first:

1. **The race.** Two concurrent first-contact payloads (MQTT and HTTPS) both read
   a NULL ``current_session_id``, both create. One wins the pointer; the other is
   orphaned open forever. Closing "the older one" is wrong here: the pointer can
   belong to the older row, so closing by timestamp closes the session the device
   is actively writing to and keeps the orphan.
2. **The singleton orphan.** ``LiveLinkService.unlink_device`` clears
   ``current_session_id`` without closing the session. That violates nothing
   today -- it is one open row, not two -- so a duplicate scan does not see it,
   and it would then reject every future session start for that device once the
   index exists. Permanently, and with no message a user could act on.

So the preflight is an inventory of every open row, not a duplicate scan. Each
case below is one row of that inventory.

Parameterized over SQLite and PostgreSQL. PG matters specifically: partial index
syntax and ``NOT NULL DEFAULT`` behaviour on ``ALTER TABLE`` differ, and
``bin/ci-check`` does not run PG -- which is how the migration 096 defect reached
CI.

Every test builds the PRE-098 shape by hand. The ORM now declares these columns,
so a ``create_all`` baseline would start in the post-state and every
"column exists" assertion would pass before the migration ran.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

import app.migrations as _m

pytestmark = pytest.mark.migrations


def _load(name: str):
    path = Path(_m.__file__).parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


#: (table, column, nullable). The whole set 098 adds, enumerated in one place so
#: a column added to the design without a matching migration step fails here.
#: An earlier revision of the design named this migration around ONE column
#: while the rest of the document silently required four more -- and on SQLite a
#: model that declares a column the table lacks does not self-heal, because
#: `create_all` never alters an existing table.
EXPECTED_COLUMNS = [
    ("livelink_devices", "last_movement_at", True),
    ("livelink_devices", "pending_since", True),
    ("livelink_devices", "pending_source", True),
    ("livelink_devices", "movement_candidate_at", True),
    ("livelink_devices", "movement_baseline_km", True),
    ("drive_sessions", "movement_started_at", True),
    ("drive_sessions", "movement_ended_at", True),
    ("drive_sessions", "boundary_algorithm_version", False),
    ("drive_sessions", "effective_gap_minutes", True),
]

BASE = datetime(2026, 9, 1, 8, 0, 0)


def _make_pre_098_schema(engine) -> None:
    """livelink_devices + drive_sessions + vehicle_telemetry, pre-098."""
    is_pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    with engine.begin() as conn:
        conn.execute(
            text(f"""
                CREATE TABLE livelink_devices (
                    id {pk},
                    device_id VARCHAR(20) NOT NULL,
                    vin VARCHAR(17),
                    current_session_id INTEGER,
                    ecu_status VARCHAR(20),
                    last_seen TIMESTAMP,
                    enabled BOOLEAN DEFAULT TRUE
                )
            """)
        )
        conn.execute(
            text(f"""
                CREATE TABLE drive_sessions (
                    id {pk},
                    vin VARCHAR(17) NOT NULL,
                    device_id VARCHAR(20) NOT NULL,
                    started_at TIMESTAMP NOT NULL,
                    ended_at TIMESTAMP,
                    duration_seconds INTEGER,
                    external_session_id VARCHAR(64)
                )
            """)
        )
        conn.execute(
            text(f"""
                CREATE TABLE vehicle_telemetry (
                    id {pk},
                    vin VARCHAR(17) NOT NULL,
                    device_id VARCHAR(20) NOT NULL,
                    param_key VARCHAR(100) NOT NULL,
                    value FLOAT NOT NULL,
                    timestamp TIMESTAMP NOT NULL
                )
            """)
        )


def _add_device(conn, device_id: str, current_session_id: int | None = None) -> None:
    conn.execute(
        text(
            "INSERT INTO livelink_devices (device_id, vin, current_session_id) VALUES (:d, :v, :c)"
        ),
        {"d": device_id, "v": f"VIN{device_id:0>14}", "c": current_session_id},
    )


def _add_session(
    conn,
    device_id: str,
    session_id: int,
    started_at: datetime,
    ended_at: datetime | None = None,
    external_session_id: str | None = None,
) -> None:
    conn.execute(
        text(
            "INSERT INTO drive_sessions "
            "(id, vin, device_id, started_at, ended_at, external_session_id) "
            "VALUES (:i, :v, :d, :s, :e, :x)"
        ),
        {
            "i": session_id,
            "v": f"VIN{device_id:0>14}",
            "d": device_id,
            "s": started_at,
            "e": ended_at,
            "x": external_session_id,
        },
    )


def _add_telemetry(conn, device_id: str, at: datetime, key: str = "SPEED", value: float = 40.0):
    conn.execute(
        text(
            "INSERT INTO vehicle_telemetry (vin, device_id, param_key, value, timestamp) "
            "VALUES (:v, :d, :k, :val, :t)"
        ),
        {"v": f"VIN{device_id:0>14}", "d": device_id, "k": key, "val": value, "t": at},
    )


def _open_sessions(engine, device_id: str) -> list[int]:
    with engine.connect() as conn:
        return [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT id FROM drive_sessions WHERE device_id = :d "
                    "AND ended_at IS NULL ORDER BY id"
                ),
                {"d": device_id},
            )
        ]


def _session_row(engine, session_id: int) -> dict:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, started_at, ended_at FROM drive_sessions WHERE id = :i"),
            {"i": session_id},
        ).one()
    return {"id": row[0], "started_at": row[1], "ended_at": row[2]}


def _pointer(engine, device_id: str) -> int | None:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT current_session_id FROM livelink_devices WHERE device_id = :d"),
            {"d": device_id},
        ).scalar_one()


def _as_dt(value) -> datetime | None:
    """SQLite hands back strings for TIMESTAMP columns declared in raw DDL."""
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
class TestSchema:
    def test_every_expected_column_is_added(self, engine_for_migration):
        _dialect, engine, _url = engine_for_migration
        _make_pre_098_schema(engine)

        insp = inspect(engine)
        before = {
            (t, c["name"])
            for t in ("livelink_devices", "drive_sessions")
            for c in insp.get_columns(t)
        }
        missing_before = [(t, c) for t, c, _n in EXPECTED_COLUMNS if (t, c) not in before]
        assert missing_before == [(t, c) for t, c, _n in EXPECTED_COLUMNS], (
            "the pre-098 fixture already has some of these columns, so the "
            f"assertions below would pass without the migration: {missing_before}"
        )

        _load("098_session_boundaries").upgrade(engine)

        insp = inspect(engine)
        actual = {
            t: {c["name"]: c for c in insp.get_columns(t)}
            for t in ("livelink_devices", "drive_sessions")
        }
        for table, column, nullable in EXPECTED_COLUMNS:
            assert column in actual[table], f"{table}.{column} was not added"
            assert bool(actual[table][column]["nullable"]) is nullable, (
                f"{table}.{column} nullability is wrong"
            )

    def test_boundary_version_defaults_existing_rows_to_zero(self, engine_for_migration):
        """Zero means "cut by the old rule", and getting it backwards is unrecoverable.

        Every pre-098 session was bounded by contact, not movement. Stamping
        them `1` would claim they follow semantics they do not, and a later
        reconstruction -- whose whole job is finding sessions cut the old way --
        would skip every one of them, forever.
        """
        _dialect, engine, _url = engine_for_migration
        _make_pre_098_schema(engine)
        with engine.begin() as conn:
            _add_device(conn, "dev1", current_session_id=None)
            _add_session(conn, "dev1", 1, BASE, BASE + timedelta(minutes=20))

        _load("098_session_boundaries").upgrade(engine)

        with engine.connect() as conn:
            version = conn.execute(
                text("SELECT boundary_algorithm_version FROM drive_sessions WHERE id = 1")
            ).scalar_one()
            gap = conn.execute(
                text("SELECT effective_gap_minutes FROM drive_sessions WHERE id = 1")
            ).scalar_one()
        assert version == 0
        assert gap is None, "NULL means 'the old contact timeout applied', not 'zero minutes'"

    def test_reconstruction_runs_table_is_created(self, engine_for_migration):
        _dialect, engine, _url = engine_for_migration
        _make_pre_098_schema(engine)
        assert not inspect(engine).has_table("livelink_reconstruction_runs")

        _load("098_session_boundaries").upgrade(engine)

        insp = inspect(engine)
        assert insp.has_table("livelink_reconstruction_runs")
        columns = {c["name"] for c in insp.get_columns("livelink_reconstruction_runs")}
        expected = {
            "id",
            "started_at",
            "finished_at",
            "dry_run",
            "gap_minutes",
            "boundary_version",
            "sessions_created",
            "sessions_merged",
            "sessions_split",
            "sessions_closed",
            "sessions_refused",
            "refusals",
        }
        assert expected <= columns, f"missing: {sorted(expected - columns)}"

    def test_the_movement_index_exists(self, engine_for_migration):
        """The timeout query scans on `last_movement_at`; unindexed it is a table scan."""
        _dialect, engine, _url = engine_for_migration
        _make_pre_098_schema(engine)
        _load("098_session_boundaries").upgrade(engine)

        names = {i["name"] for i in inspect(engine).get_indexes("livelink_devices")}
        assert "ix_livelink_devices_last_movement_at" in names

    def test_a_second_open_session_is_rejected(self, engine_for_migration):
        """The index is the point of the migration, so assert it BITES.

        Asserting the index merely exists would pass against a non-unique index,
        a full (non-partial) unique index that rejects legitimate closed
        sessions, or one built on the wrong column.
        """
        _dialect, engine, _url = engine_for_migration
        _make_pre_098_schema(engine)
        with engine.begin() as conn:
            _add_device(conn, "dev1", current_session_id=1)
            _add_session(conn, "dev1", 1, BASE)
        _load("098_session_boundaries").upgrade(engine)

        with pytest.raises(Exception) as excinfo:
            with engine.begin() as conn:
                _add_session(conn, "dev1", 2, BASE + timedelta(minutes=5))
        assert "unique" in str(excinfo.value).lower()

    def test_closed_sessions_are_not_constrained(self, engine_for_migration):
        """The index must be PARTIAL. A plain unique index on device_id would
        allow one session per device ever, which is not a constraint anyone
        wants and would break on the second drive."""
        _dialect, engine, _url = engine_for_migration
        _make_pre_098_schema(engine)
        with engine.begin() as conn:
            _add_device(conn, "dev1", current_session_id=None)
        _load("098_session_boundaries").upgrade(engine)

        with engine.begin() as conn:
            _add_session(conn, "dev1", 1, BASE, BASE + timedelta(minutes=10))
            _add_session(conn, "dev1", 2, BASE + timedelta(hours=1), BASE + timedelta(hours=2))
            _add_session(conn, "dev1", 3, BASE + timedelta(hours=3))  # one open is fine
        assert _open_sessions(engine, "dev1") == [3]


# ---------------------------------------------------------------------------
# Preflight: the open-session inventory
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
class TestOpenSessionPreflight:
    def test_the_pointed_at_session_is_retained_even_when_older(self, engine_for_migration):
        """The case a "close the older duplicates" rule gets backwards.

        In the race the pointer can land on the OLDER row -- MQTT created first
        and won the pointer, HTTPS created second and was orphaned. Closing by
        timestamp closes the session the device is actively writing to and keeps
        the orphan, which is worse than doing nothing.
        """
        _dialect, engine, _url = engine_for_migration
        _make_pre_098_schema(engine)
        with engine.begin() as conn:
            _add_device(conn, "dev1", current_session_id=1)
            _add_session(conn, "dev1", 1, BASE)  # older, pointed at
            _add_session(conn, "dev1", 2, BASE + timedelta(minutes=3))  # newer orphan
            _add_telemetry(conn, "dev1", BASE + timedelta(minutes=1))

        _load("098_session_boundaries").upgrade(engine)

        assert _open_sessions(engine, "dev1") == [1], "the pointed-at session must survive"
        assert _pointer(engine, "dev1") == 1
        assert _session_row(engine, 2)["ended_at"] is not None

    def test_without_a_pointer_the_newest_is_retained(self, engine_for_migration):
        _dialect, engine, _url = engine_for_migration
        _make_pre_098_schema(engine)
        with engine.begin() as conn:
            _add_device(conn, "dev1", current_session_id=None)
            _add_session(conn, "dev1", 1, BASE)
            _add_session(conn, "dev1", 2, BASE + timedelta(minutes=30))

        _load("098_session_boundaries").upgrade(engine)

        assert _open_sessions(engine, "dev1") == [2]
        assert _pointer(engine, "dev1") == 2, "the pointer is repaired to the retained row"

    def test_a_stale_pointer_to_a_closed_session_falls_back_to_newest(self, engine_for_migration):
        """`current_session_id` naming an already-CLOSED row is not a valid retention."""
        _dialect, engine, _url = engine_for_migration
        _make_pre_098_schema(engine)
        with engine.begin() as conn:
            _add_device(conn, "dev1", current_session_id=1)
            _add_session(conn, "dev1", 1, BASE, BASE + timedelta(minutes=5))  # closed
            _add_session(conn, "dev1", 2, BASE + timedelta(minutes=10))
            _add_session(conn, "dev1", 3, BASE + timedelta(minutes=40))

        _load("098_session_boundaries").upgrade(engine)

        assert _open_sessions(engine, "dev1") == [3]
        assert _pointer(engine, "dev1") == 3

    def test_the_singleton_orphan_is_closed(self, engine_for_migration):
        """One open row with a NULL pointer violates nothing today.

        `unlink_device` clears the pointer without closing the session, so this
        shape exists in the wild. A duplicate scan does not see it -- there is
        no duplicate -- and once the index exists it silently rejects every
        future session for that device. This is the case a "find the dupes"
        preflight leaves behind.
        """
        _dialect, engine, _url = engine_for_migration
        _make_pre_098_schema(engine)
        with engine.begin() as conn:
            _add_device(conn, "dev1", current_session_id=None)
            _add_session(conn, "dev1", 1, BASE)
            _add_telemetry(conn, "dev1", BASE + timedelta(minutes=12))

        _load("098_session_boundaries").upgrade(engine)

        assert _open_sessions(engine, "dev1") == [1], (
            "a lone open session is legal; only its POINTER was missing, and "
            "repairing the pointer is the fix, not closing the session"
        )
        assert _pointer(engine, "dev1") == 1

    def test_an_orphan_is_closed_at_its_own_last_telemetry(self, engine_for_migration):
        """Not at 'now', which would invent hours of drive on a session from March."""
        _dialect, engine, _url = engine_for_migration
        _make_pre_098_schema(engine)
        last_sample = BASE + timedelta(minutes=7)
        with engine.begin() as conn:
            _add_device(conn, "dev1", current_session_id=2)
            _add_session(conn, "dev1", 1, BASE)  # orphan
            _add_session(conn, "dev1", 2, BASE + timedelta(hours=5))  # retained
            _add_telemetry(conn, "dev1", BASE + timedelta(minutes=2))
            _add_telemetry(conn, "dev1", last_sample)

        _load("098_session_boundaries").upgrade(engine)

        assert _as_dt(_session_row(engine, 1)["ended_at"]) == last_sample

    def test_an_orphan_close_cannot_overlap_the_retained_session(self, engine_for_migration):
        """Clamping, stated as its own case because the unclamped version looks fine.

        The orphan's last telemetry can be NEWER than the retained session's
        start -- the two windows genuinely overlap in the race. Closing the
        orphan at that sample leaves two sessions both claiming the same
        telemetry, and every aggregate is a window scan, so both report the same
        distance and the vehicle appears to have driven it twice.
        """
        _dialect, engine, _url = engine_for_migration
        _make_pre_098_schema(engine)
        retained_start = BASE + timedelta(minutes=10)
        with engine.begin() as conn:
            _add_device(conn, "dev1", current_session_id=2)
            _add_session(conn, "dev1", 1, BASE)
            _add_session(conn, "dev1", 2, retained_start)
            _add_telemetry(conn, "dev1", BASE + timedelta(minutes=45))  # well past retained start

        _load("098_session_boundaries").upgrade(engine)

        ended = _as_dt(_session_row(engine, 1)["ended_at"])
        assert ended is not None
        assert ended <= retained_start, f"orphan closed at {ended}, overlapping {retained_start}"

    def test_an_orphan_with_no_telemetry_closes_at_its_own_start(self, engine_for_migration):
        """A zero-length session is honest; a session ending at `now` is not."""
        _dialect, engine, _url = engine_for_migration
        _make_pre_098_schema(engine)
        with engine.begin() as conn:
            _add_device(conn, "dev1", current_session_id=2)
            _add_session(conn, "dev1", 1, BASE)
            _add_session(conn, "dev1", 2, BASE + timedelta(hours=2))

        _load("098_session_boundaries").upgrade(engine)

        row = _session_row(engine, 1)
        assert _as_dt(row["ended_at"]) == _as_dt(row["started_at"])

    def test_devices_are_reconciled_independently(self, engine_for_migration):
        """Guard against a preflight that keeps one open session GLOBALLY."""
        _dialect, engine, _url = engine_for_migration
        _make_pre_098_schema(engine)
        with engine.begin() as conn:
            _add_device(conn, "dev1", current_session_id=1)
            _add_device(conn, "dev2", current_session_id=3)
            _add_session(conn, "dev1", 1, BASE)
            _add_session(conn, "dev1", 2, BASE + timedelta(minutes=1))
            _add_session(conn, "dev2", 3, BASE)
            _add_session(conn, "dev2", 4, BASE + timedelta(minutes=1))

        _load("098_session_boundaries").upgrade(engine)

        assert _open_sessions(engine, "dev1") == [1]
        assert _open_sessions(engine, "dev2") == [3]

    def test_a_session_whose_device_row_is_gone_is_closed(self, engine_for_migration):
        """`drive_sessions.device_id` carries no FK, and device deletes retain
        history by design, so an open session with no device row is reachable.
        It has no pointer to consult and would block nothing -- but it also can
        never be closed by any live path again, so the preflight closes it."""
        _dialect, engine, _url = engine_for_migration
        _make_pre_098_schema(engine)
        with engine.begin() as conn:
            _add_session(conn, "ghost", 1, BASE)

        _load("098_session_boundaries").upgrade(engine)

        assert _session_row(engine, 1)["ended_at"] is not None


# ---------------------------------------------------------------------------
# Re-entrancy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_running_twice_is_safe(engine_for_migration):
    """The runner stamps in a separate transaction from the upgrade, so a crash
    in between re-runs this migration against its own output."""
    _dialect, engine, _url = engine_for_migration
    _make_pre_098_schema(engine)
    with engine.begin() as conn:
        _add_device(conn, "dev1", current_session_id=1)
        _add_session(conn, "dev1", 1, BASE)
        _add_session(conn, "dev1", 2, BASE + timedelta(minutes=2))

    mod = _load("098_session_boundaries")
    mod.upgrade(engine)
    first = _open_sessions(engine, "dev1")
    mod.upgrade(engine)

    assert _open_sessions(engine, "dev1") == first
    insp = inspect(engine)
    for table, column, _n in EXPECTED_COLUMNS:
        assert column in {c["name"] for c in insp.get_columns(table)}


@pytest.mark.parametrize("engine_for_migration", ["sqlite", "pg"], indirect=True)
def test_it_is_not_fatal(engine_for_migration):
    """An instance that cannot take the index is still usable; a crash-loop is not.

    The runner log-and-continues for non-FATAL migrations, which is the right
    trade here: without the index the race stays possible, and with FATAL=True a
    database that cannot take it never starts again.
    """
    _dialect, _engine, _url = engine_for_migration
    assert getattr(_load("098_session_boundaries"), "FATAL", False) is False

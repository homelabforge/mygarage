"""Durable movement state, session provenance, and one open session per device.

The schema half of the session-boundary rework. A drive session used to open on
*contact* -- any sign the dongle could reach the broker -- and a parked WiCAN
publishes a battery-voltage heartbeat roughly every 95 minutes, so 83% of
recorded sessions (2,975 of 3,238 on this instance) were a heartbeat rather than
a drive, while real drives out of broker range were missed entirely.

Deciding sessions on *movement* instead needs state that outlives a request:
the MQTT subscriber, the HTTPS route and the scheduler are three execution
contexts, so an in-memory movement candidate is invisible to two of them and is
lost on every container restart. Hence five columns on ``livelink_devices``.

Sessions also gain provenance. Every row that exists today was cut by the old
rule, so ``boundary_algorithm_version`` defaults to **0** -- "pre-098
semantics". Getting that default backwards would make every historic session
look already-correct and be skipped by any future pass over history, forever.

NOT FATAL
---------
Deliberately. The partial unique index is the one step that can fail on live
data, and an instance without it is still a working instance -- the race it
prevents is rare -- whereas a crash-looping instance is not usable at all. The
runner logs and continues.

THE PREFLIGHT IS AN INVENTORY, NOT A DUPLICATE SCAN
---------------------------------------------------
``uq_drive_sessions_open_per_device`` can fail on existing data, and "close the
older duplicates" is not sufficient:

- ``livelink_devices.current_session_id`` points at one open session, and in the
  race that pointer can belong to the OLDER row. Closing by timestamp then
  closes the session the device is actively writing to and keeps the orphan.
- There are also **singleton** orphans: ``LiveLinkService.unlink_device`` clears
  the pointer without closing the session. That violates nothing today, so a
  duplicate scan does not see it -- but the session can never be closed by any
  live path again, and it would reject every future session start for that
  device once the index exists.

So every open row is inventoried, the retained row is the one the pointer names
(if open) or else the newest, every other open row is closed at its own last
telemetry sample clamped against the retained session's start, and the pointer
is repaired in the same transaction.

Back up before deploying, with the backup API (``POST /api/backup/create-full``),
not ``cp``: MyGarage runs in WAL mode and a plain file copy of a database with a
live WAL sidecar is torn but plausible.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

FATAL = False

#: (table, column, DDL type). Nullable in every case except the version column,
#: which carries a NOT NULL DEFAULT 0 -- see the module docstring.
_NEW_COLUMNS: tuple[tuple[str, str, str], ...] = (
    # Movement state, per device. All five reset together (see the state
    # machine in SessionService); splitting them across migrations is what left
    # an earlier revision of the design unbuildable from its own schema.
    ("livelink_devices", "last_movement_at", "TIMESTAMP"),
    ("livelink_devices", "pending_since", "TIMESTAMP"),
    ("livelink_devices", "pending_source", "VARCHAR(10)"),
    ("livelink_devices", "movement_candidate_at", "TIMESTAMP"),
    ("livelink_devices", "movement_baseline_km", "NUMERIC(10,2)"),
    # Session provenance and true movement bounds.
    ("drive_sessions", "movement_started_at", "TIMESTAMP"),
    ("drive_sessions", "movement_ended_at", "TIMESTAMP"),
    ("drive_sessions", "boundary_algorithm_version", "INTEGER NOT NULL DEFAULT 0"),
    ("drive_sessions", "effective_gap_minutes", "INTEGER"),
)


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def _add_missing_columns(conn, inspector) -> int:
    """``ALTER TABLE ADD COLUMN`` for each absent column. Identical on both dialects.

    ``NOT NULL DEFAULT 0`` on ADD COLUMN is accepted by SQLite (3.32+) and
    PostgreSQL alike and fills existing rows, which is what makes
    ``boundary_algorithm_version`` land as 0 on history without a second UPDATE.
    """
    added = 0
    for table, column, ddl_type in _NEW_COLUMNS:
        if not inspector.has_table(table):
            print(f"  → {table} missing; skip {column}")
            continue
        if column in {c["name"] for c in inspector.get_columns(table)}:
            continue
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
        print(f"  ✓ Added {table}.{column}")
        added += 1
    return added


def _last_telemetry_by_device(conn) -> dict[str, datetime]:
    """The newest telemetry timestamp per device, for closing orphans honestly.

    One grouped query rather than one per orphan: a database with a few hundred
    orphans should not issue a few hundred round trips during startup.
    """
    rows = conn.execute(
        text("SELECT device_id, MAX(timestamp) FROM vehicle_telemetry GROUP BY device_id")
    )
    out: dict[str, datetime] = {}
    for device_id, stamp in rows:
        if device_id is None or stamp is None:
            continue
        out[device_id] = (
            stamp if isinstance(stamp, datetime) else datetime.fromisoformat(str(stamp))
        )
    return out


def _coerce(value) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _preflight_open_sessions(conn, inspector) -> tuple[int, int]:
    """Reconcile every open session so the partial unique index can be created.

    Returns ``(sessions_closed, pointers_repaired)``.
    """
    if not inspector.has_table("drive_sessions"):
        return 0, 0

    open_rows = list(
        conn.execute(
            text(
                "SELECT id, device_id, started_at FROM drive_sessions "
                "WHERE ended_at IS NULL ORDER BY device_id, started_at, id"
            )
        )
    )
    if not open_rows:
        return 0, 0

    pointers: dict[str, int | None] = {}
    if inspector.has_table("livelink_devices"):
        pointers = {
            row[0]: row[1]
            for row in conn.execute(
                text("SELECT device_id, current_session_id FROM livelink_devices")
            )
        }

    last_seen_sample = (
        _last_telemetry_by_device(conn) if inspector.has_table("vehicle_telemetry") else {}
    )

    by_device: dict[str, list[tuple[int, datetime | None]]] = {}
    for session_id, device_id, started_at in open_rows:
        by_device.setdefault(device_id, []).append((session_id, _coerce(started_at)))

    closed = 0
    repaired = 0
    for device_id, sessions in sorted(by_device.items()):
        open_ids = {sid for sid, _ in sessions}
        pointed_at = pointers.get(device_id)

        if device_id not in pointers:
            # No device row at all. `drive_sessions.device_id` carries no FK and
            # device deletion deliberately retains history, so this is reachable
            # -- and no live path can ever close these again.
            retained_id = None
        elif pointed_at in open_ids:
            retained_id = pointed_at
        else:
            # Newest by started_at, ties broken by id. A NULL started_at cannot
            # happen (NOT NULL) but sorts first defensively rather than raising.
            retained_id = max(sessions, key=lambda pair: (pair[1] or datetime.min, pair[0]))[0]

        retained_start = next((start for sid, start in sessions if sid == retained_id), None)

        for session_id, started_at in sessions:
            if session_id == retained_id:
                continue
            # Its own last telemetry, not `now`: closing a session from March at
            # the upgrade timestamp would invent months of drive.
            end_at = last_seen_sample.get(device_id) or started_at
            if started_at is not None and (end_at is None or end_at < started_at):
                end_at = started_at
            # Clamped against the retained session, because the two windows
            # genuinely overlap in the race. Two sessions claiming the same
            # telemetry both report the same distance, and every aggregate here
            # is a window scan.
            if retained_start is not None and end_at is not None and end_at > retained_start:
                end_at = retained_start
            duration = None
            if started_at is not None and end_at is not None:
                duration = max(0, int((end_at - started_at).total_seconds()))
            conn.execute(
                text(
                    "UPDATE drive_sessions SET ended_at = :e, duration_seconds = :d WHERE id = :i"
                ),
                {"e": end_at, "d": duration, "i": session_id},
            )
            closed += 1
            print(f"  ✓ Closed orphaned open session {session_id} ({device_id}) at {end_at}")

        if retained_id is not None and pointed_at != retained_id:
            conn.execute(
                text("UPDATE livelink_devices SET current_session_id = :s WHERE device_id = :d"),
                {"s": retained_id, "d": device_id},
            )
            repaired += 1
            print(f"  ✓ Repaired {device_id}.current_session_id -> {retained_id}")

    return closed, repaired


def _create_indexes(conn, inspector) -> None:
    """The movement index and the partial unique index.

    ``CREATE UNIQUE INDEX ... WHERE`` is supported by SQLite and PostgreSQL in
    the same syntax, so no dialect branch is needed here.
    """
    if inspector.has_table("livelink_devices"):
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_livelink_devices_last_movement_at "
                "ON livelink_devices (last_movement_at)"
            )
        )
    if inspector.has_table("drive_sessions"):
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_drive_sessions_open_per_device "
                "ON drive_sessions (device_id) WHERE ended_at IS NULL"
            )
        )
        print("  ✓ One open session per device is now a constraint")


def upgrade(engine=None) -> None:
    """Add the columns, reconcile open sessions, then take the index."""
    if engine is None:
        engine = _get_fallback_engine()

    inspector = inspect(engine)

    # One transaction: the runner stamps `schema_migrations` in a SEPARATE
    # transaction, so a crash between two non-transactional steps would leave a
    # schema matching neither branch of the re-entrancy check. SQLite supports
    # transactional DDL, so this holds on both dialects.
    with engine.begin() as conn:
        _add_missing_columns(conn, inspector)

        # Re-inspect: the preflight and index steps read columns this
        # transaction just added.
        inspector = inspect(engine)

        closed, repaired = _preflight_open_sessions(conn, inspector)
        if closed or repaired:
            print(f"  ✓ Preflight: closed {closed} orphan(s), repaired {repaired} pointer(s)")

        _create_indexes(conn, inspector)

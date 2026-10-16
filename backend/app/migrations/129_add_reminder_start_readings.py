"""Store the readings an unanchored reminder counts from (PR #216).

A hand-made reminder counted from the reading nearest the day it was made,
looked up on every read, so a reading added or corrected that day moved its
start and held the bar at zero. New reminders store both current readings
when made; this adds the columns and fills them for pending unanchored rows
from the latest reading dated on or before the creation day and entered
before the reminder.

It can't undo a reading changed in place after the reminder was made (a
same-day fill-up taking over the day's row, LiveLink's daily row, the manual
hours upsert): that row keeps its first created_at with the later figure.

The creation day reads created_at as UTC, like the app does, so a PostgreSQL
server on a non-UTC session clock shifts it the same way it shifts the app.

FATAL: the ORM maps both columns, so a silent skip would 500 every reminder
read.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import (
    Connection,
    Date,
    DateTime,
    Engine,
    Integer,
    bindparam,
    create_engine,
    inspect,
    text,
)

from app.utils.household_time import resolve_zone

FATAL = True

logger = logging.getLogger(__name__)

#: (column, DDL), at the scales of anchor_odometer_km and anchor_hours.
_COLUMNS: tuple[tuple[str, str], ...] = (
    ("start_odometer_km", "NUMERIC(10, 2)"),
    ("start_hours", "NUMERIC(10, 1)"),
)

_PENDING_UNANCHORED = text(
    "SELECT id, created_at FROM vehicle_reminders "
    "WHERE status = 'pending' AND (anchor_kind IS NULL OR anchor_date IS NULL) "
    "AND (start_odometer_km IS NULL OR start_hours IS NULL)"
).columns(id=Integer, created_at=DateTime)

# RETURNING hands back the new start (NULL when no reading qualified, no row when
# one was already stored), so the log counts rows that actually gained one.
_FILL_ODOMETER = text(
    """
    UPDATE vehicle_reminders SET start_odometer_km = (
        SELECT o.odometer_km FROM odometer_records o
        WHERE o.vin = vehicle_reminders.vin
          AND o.date <= :day
          AND (o.created_at IS NULL OR o.created_at <= vehicle_reminders.created_at)
        ORDER BY o.date DESC, o.odometer_km DESC, o.id DESC
        LIMIT 1
    )
    WHERE id = :id AND start_odometer_km IS NULL
    RETURNING start_odometer_km
    """
).bindparams(bindparam("day", type_=Date))

# Highest first: current hours is the highest reading, so a later-dated lower
# correction doesn't win.
_FILL_HOURS = text(
    """
    UPDATE vehicle_reminders SET start_hours = (
        SELECT h.engine_hours FROM hours_records h
        WHERE h.vin = vehicle_reminders.vin
          AND h.date <= :day
          AND (h.created_at IS NULL OR h.created_at <= vehicle_reminders.created_at)
        ORDER BY h.engine_hours DESC, h.date DESC, h.id DESC
        LIMIT 1
    )
    WHERE id = :id AND start_hours IS NULL
    RETURNING start_hours
    """
).bindparams(bindparam("day", type_=Date))


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def _household_day(created_at: datetime, zone: ZoneInfo) -> date:
    """household_date's rule: a naive timestamp is UTC."""
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return created_at.astimezone(zone).date()


def _backfill(conn: Connection, zone: ZoneInfo) -> int:
    """Fill the missing starts on pending unanchored reminders and return how many
    gained at least one. A start already stored is never overwritten."""
    inspector = inspect(conn)
    has_odometer = inspector.has_table("odometer_records")
    has_hours = inspector.has_table("hours_records")
    if not (has_odometer or has_hours):
        return 0

    filled = 0
    for reminder_id, created_at in conn.execute(_PENDING_UNANCHORED).all():
        if created_at is None:
            continue
        params = {"id": reminder_id, "day": _household_day(created_at, zone)}
        gained = False
        if has_odometer:
            gained |= conn.execute(_FILL_ODOMETER, params).scalar() is not None
        if has_hours:
            gained |= conn.execute(_FILL_HOURS, params).scalar() is not None
        if gained:
            filled += 1
    return filled


def upgrade(engine: Engine | None = None) -> None:
    """Add the start columns where missing and backfill pending unanchored reminders."""
    if engine is None:
        engine = _get_fallback_engine()

    inspector = inspect(engine)
    if not inspector.has_table("vehicle_reminders"):
        return
    existing = {c["name"] for c in inspector.get_columns("vehicle_reminders")}
    missing = [(name, ddl) for name, ddl in _COLUMNS if name not in existing]
    has_settings = inspector.has_table("settings")

    # Not atomic on SQLite (pysqlite commits the DDL), so a rerun after a failed
    # backfill finds the columns and finishes the rows the IS NULL guards left.
    with engine.begin() as conn:
        value = None
        if has_settings:
            value = conn.execute(text("SELECT value FROM settings WHERE key = 'timezone'")).scalar()
        zone = resolve_zone(value)
        for name, ddl in missing:
            conn.execute(text(f"ALTER TABLE vehicle_reminders ADD COLUMN {name} {ddl}"))
            logger.info("Added vehicle_reminders.%s", name)
        filled = _backfill(conn, zone)
    logger.info("Filled start readings on %d pending unanchored reminders", filled)


def downgrade() -> None:  # pragma: no cover
    """Rollback not supported."""
    raise NotImplementedError("Migration 129 is forward-only.")


if __name__ == "__main__":
    upgrade()

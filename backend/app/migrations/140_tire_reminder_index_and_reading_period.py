"""One live low-tread reminder per tire, by index, and clear the readings' unused period (G3a-17, D2).

The design always meant ``uq_reminder_source_tire_live`` to exist, and it never
did, so the low-tread sync collapsed duplicates by hand. This closes every
extra pending row on one ``(source, tire_id)``, keeping the lowest id as the
sync did, then builds the index so a racing duplicate can't land again. Only
rows the index covers are touched: a reminder a person wrote, or one from a
rule, has no source and no tire, and is left alone.

``tire_readings.mount_period_id`` is cleared too. No live writer set it after
097's backfill; only the JSON backup import put it back, until this batch. So
some readings had one and most didn't, and readings are matched to periods by
date and position everywhere it counts. The column stays.

Not FATAL, so the app still boots, but a failed dedupe or index build raises:
the runner logs it, leaves 140 unstamped and runs it again next boot, and any
migration after 140 waits until it lands. The sync doesn't collapse duplicates
any more, so until 140 lands any old duplicate reminders stay pending, and a
stamped-but-failed 140 would leave them that way for good. Clearing the
periods runs first and only logs a failure: it's idempotent, and it shouldn't
hold up the retry.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

INDEX = "uq_reminder_source_tire_live"
#: The index's WHERE. The model declares the same text, so create_all matches.
LIVE = "source IS NOT NULL AND tire_id IS NOT NULL AND status = 'pending'"


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    # hide_parameters: a failed statement's message leaves out its bound values.
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}", hide_parameters=True)
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}", hide_parameters=True)


def _dedupe_and_index(engine: Engine) -> None:
    """Close each live duplicate but the lowest id, then build the partial unique index."""
    inspector = inspect(engine)
    if not inspector.has_table("vehicle_reminders"):
        logger.info("140: vehicle_reminders missing; no index to build")
        return
    if not {"source", "tire_id", "status"} <= {
        c["name"] for c in inspector.get_columns("vehicle_reminders")
    }:
        logger.info("140: vehicle_reminders.source, tire_id or status missing; no index to build")
        return
    with engine.begin() as conn:
        # The keeper is never closed, so it doesn't matter whether a dialect
        # sees this statement's own updates.
        closed = conn.execute(
            text(
                "UPDATE vehicle_reminders SET status = 'done'"
                f" WHERE {LIVE}"
                " AND EXISTS (SELECT 1 FROM vehicle_reminders AS keeper"
                " WHERE keeper.source = vehicle_reminders.source"
                " AND keeper.tire_id = vehicle_reminders.tire_id"
                " AND keeper.status = 'pending'"
                " AND keeper.id < vehicle_reminders.id)"
            )
        ).rowcount
        built = INDEX not in {ix["name"] for ix in inspect(conn).get_indexes("vehicle_reminders")}
        if built:
            conn.execute(
                text(
                    f"CREATE UNIQUE INDEX {INDEX} ON vehicle_reminders (source, tire_id)"
                    f" WHERE {LIVE}"
                )
            )
    logger.info(
        "140: closed %d duplicate tire reminder(s); %s %s",
        closed,
        "built" if built else "already had",
        INDEX,
    )


def _clear_reading_periods(engine: Engine) -> None:
    """NULL every reading's mount_period_id."""
    inspector = inspect(engine)
    if not inspector.has_table("tire_readings"):
        logger.info("140: tire_readings missing; no periods to clear")
        return
    if "mount_period_id" not in {c["name"] for c in inspector.get_columns("tire_readings")}:
        logger.info("140: tire_readings.mount_period_id missing; no periods to clear")
        return
    with engine.begin() as conn:
        cleared = conn.execute(
            text(
                "UPDATE tire_readings SET mount_period_id = NULL WHERE mount_period_id IS NOT NULL"
            )
        ).rowcount
    logger.info("140: cleared the mount period on %d reading(s)", cleared)


def upgrade(engine: Engine | None = None) -> None:
    """Clear the periods (a failure is logged), then dedupe and index (a failure raises)."""
    if engine is None:
        engine = _get_fallback_engine()
    try:
        _clear_reading_periods(engine)
    except SQLAlchemyError as e:
        logger.error("140: reading mount periods not cleared, they stay: %s", e, exc_info=True)
    # No catch here: raising leaves 140 unstamped, so a retry next boot can still
    # close the old duplicates.
    _dedupe_and_index(engine)


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError("Migration 140 is forward-only.")


if __name__ == "__main__":
    upgrade()

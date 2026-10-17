"""Recompute the trips migration 130 left waiting (#223).

Migrations run on a sync engine and can't call the async session code, so 130
lists the closed Torque trips whose coolant, RPM and speed it moved onto
readable keys, and the app recomputes them once, at the next start.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.settings import Setting
from app.models.vehicle import Vehicle
from app.models.vehicle_telemetry import VehicleTelemetry
from app.services.livelink_service import LiveLinkService
from app.services.session_service import SessionService
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)

#: The settings row migration 130 writes: a JSON list of drive_sessions ids.
PENDING_KEY = "torque_session_repair"

#: Ids per SELECT, well under SQLite's bound-parameter limit.
_CHUNK = 500


def _cutoff(oldest: datetime | None, now: datetime, retention_days: int) -> datetime | None:
    """The earliest start a trip can have and still hold every reading it had.

    Each bound is safe on its own most of the time: the oldest reading unless an
    old reading landed late, now minus retention unless retention was raised
    after a prune. The later of the two only fails when both happen (D13). None
    when there's no telemetry left at all.
    """
    if oldest is None:
        return None
    return max(oldest, now - timedelta(days=retention_days))


async def _oldest_reading(db: AsyncSession) -> datetime | None:
    """The oldest telemetry on file, as one indexed (vin, timestamp) lookup per vehicle."""
    oldest: datetime | None = None
    for vin in (await db.execute(select(Vehicle.vin))).scalars().all():
        found = (
            await db.execute(
                select(func.min(VehicleTelemetry.timestamp)).where(VehicleTelemetry.vin == vin)
            )
        ).scalar()
        if found is not None and (oldest is None or found < oldest):
            oldest = found
    return oldest


async def recompute_pending_sessions(db: AsyncSession) -> int:
    """Run refresh_aggregates on each listed trip it can redo whole, then drop the list.

    A trip counts only if it started at or after `_cutoff`: one that lost readings
    to pruning keeps the stats it has, since a recompute would read what's left
    alone. One commit; returns how many trips it recomputed.
    """
    row = await db.get(Setting, PENDING_KEY)
    if row is None:
        return 0
    try:
        ids = [int(i) for i in json.loads(row.value or "[]")]
    except TypeError, ValueError:
        logger.warning("Dropping an unreadable %s row", PENDING_KEY)
        ids = []
    if not ids:
        await db.delete(row)
        await db.commit()
        return 0
    cutoff = _cutoff(
        await _oldest_reading(db), utc_now(), await LiveLinkService(db).get_retention_days()
    )
    service = SessionService(db)
    done = skipped = 0
    for start in range(0, len(ids), _CHUNK):
        trips = (
            (
                await db.execute(
                    select(DriveSession)
                    .where(
                        DriveSession.id.in_(ids[start : start + _CHUNK]),
                        DriveSession.ended_at.is_not(None),
                    )
                    .order_by(DriveSession.id)
                )
            )
            .scalars()
            .all()
        )
        for trip in trips:
            if cutoff is None or trip.started_at < cutoff:
                skipped += 1
                continue
            await service.refresh_aggregates(trip)
            done += 1
    await db.delete(row)
    await db.commit()
    logger.info(
        "Recomputed %d older Torque trip(s) after migration 130; left %d that may have lost readings to pruning",
        done,
        skipped,
    )
    return done

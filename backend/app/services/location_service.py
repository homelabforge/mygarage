"""Location service: GPS breadcrumb writes + trip read-queries for Torque-sourced drives (#118)."""

import logging
import math
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import is_sqlite
from app.models.drive_session import DriveSession
from app.models.location_point import LocationPoint
from app.utils.datetime_utils import utc_now

if is_sqlite:
    from sqlalchemy.dialects.sqlite import insert as dialect_insert
else:
    from sqlalchemy.dialects.postgresql import insert as dialect_insert

logger = logging.getLogger(__name__)

_EARTH_RADIUS_KM = 6371.0088


class LocationService:
    """Writes GPS breadcrumb points and serves trip-level read-queries."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def record_point(
        self,
        vin: str,
        device_id: str,
        drive_session_id: int | None,
        timestamp: datetime,
        latitude: Decimal,
        longitude: Decimal,
        speed: Decimal | None = None,
        heading: Decimal | None = None,
        altitude: Decimal | None = None,
    ) -> bool:
        """Insert one `location_points` row (source='torque'), deduping on
        (vin, timestamp, source). Does NOT commit — the caller owns the transaction.

        Returns True if a new row was inserted, False if it was a duplicate.
        """
        ts = timestamp.replace(tzinfo=None) if timestamp.tzinfo is not None else timestamp
        stmt = (
            dialect_insert(LocationPoint)
            .values(
                vin=vin,
                drive_session_id=drive_session_id,
                source="torque",
                timestamp=ts,
                latitude=latitude,
                longitude=longitude,
                speed=speed,
                heading=heading,
                altitude=altitude,
            )
            .on_conflict_do_nothing(index_elements=["vin", "timestamp", "source"])
        )
        result = await self.db.execute(stmt)
        return bool(result.rowcount)

    async def get_trips(self, vin: str, limit: int = 50) -> list[dict]:
        """Return sessions that have >=1 location point, newest first, each with
        {session_id, started_at, ended_at, duration_seconds, distance_km, point_count}.
        """
        rows = (
            await self.db.execute(
                select(
                    DriveSession.id,
                    DriveSession.started_at,
                    DriveSession.ended_at,
                    DriveSession.duration_seconds,
                    DriveSession.distance_km,
                    func.count(LocationPoint.id).label("point_count"),
                )
                .join(LocationPoint, LocationPoint.drive_session_id == DriveSession.id)
                .where(DriveSession.vin == vin)
                .group_by(DriveSession.id)
                .order_by(DriveSession.started_at.desc())
                .limit(limit)
            )
        ).all()
        return [
            {
                "session_id": r.id,
                "started_at": r.started_at,
                "ended_at": r.ended_at,
                "duration_seconds": r.duration_seconds,
                "distance_km": r.distance_km,
                "point_count": r.point_count,
            }
            for r in rows
        ]

    async def get_trip_points(self, vin: str, session_id: int) -> list[LocationPoint]:
        """Return a session's points ordered by timestamp ascending, scoped to
        vin (defence-in-depth even though the read gate already checked vin).
        """
        return list(
            (
                await self.db.execute(
                    select(LocationPoint)
                    .where(LocationPoint.vin == vin, LocationPoint.drive_session_id == session_id)
                    .order_by(LocationPoint.timestamp.asc())
                )
            )
            .scalars()
            .all()
        )

    async def get_last_location(self, vin: str) -> LocationPoint | None:
        """Return the most recent location point for the vin, or None."""
        return (
            await self.db.execute(
                select(LocationPoint)
                .where(LocationPoint.vin == vin)
                .order_by(LocationPoint.timestamp.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def prune_old(self, retention_days: int) -> int:
        """Delete location_points older than retention period.

        Returns count of deleted rows.
        """
        cutoff = utc_now() - timedelta(days=retention_days)

        # Count first for logging
        count_result = await self.db.execute(
            select(func.count(LocationPoint.id)).where(LocationPoint.timestamp < cutoff)
        )
        count_row = count_result.first()
        to_delete = count_row[0] if count_row else 0

        if to_delete > 0:
            await self.db.execute(delete(LocationPoint).where(LocationPoint.timestamp < cutoff))
            await self.db.commit()
            logger.info("Pruned %d location points older than %d days", to_delete, retention_days)

        return to_delete

    @staticmethod
    def haversine_km(points: Sequence[tuple[float, float]]) -> Decimal:
        """Total great-circle distance (km) across consecutive (lat, lon) pairs.

        Intermediate trig is float (this is a derived aggregate, not a stored
        unit column); the result is cast to Decimal, quantized to 2 dp, at the
        boundary. Empty or single-point input has no consecutive pair -> 0.
        """
        total = 0.0
        for (lat1, lon1), (lat2, lon2) in zip(points, points[1:]):
            p1, p2 = math.radians(lat1), math.radians(lat2)
            dphi = math.radians(lat2 - lat1)
            dlmb = math.radians(lon2 - lon1)
            a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
            total += 2 * _EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))
        return Decimal(str(round(total, 2)))

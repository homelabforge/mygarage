"""Read side of TelemetryService: queries, retention and daily summaries."""

import logging
from datetime import date, datetime, timedelta
from typing import Any, cast

from sqlalchemy import Date, delete, func, inspect, select, tuple_
from sqlalchemy.engine import CursorResult

from app.database import is_sqlite
from app.models.vehicle_telemetry import (
    TelemetryDailySummary,
    VehicleTelemetry,
    VehicleTelemetryLatest,
)
from app.services.telemetry.base import TelemetryBase
from app.utils.datetime_utils import utc_now
from app.utils.household_time import household_day_utc_bounds

if is_sqlite:
    from sqlalchemy.dialects.sqlite import insert as dialect_insert
else:
    from sqlalchemy.dialects.postgresql import insert as dialect_insert

logger = logging.getLogger(__name__)

#: How far a param's newest sample may trail the vehicle's newest sample before
#: it stops counting as live. Generous on purpose: every reported param is
#: upserted on every payload regardless of its storage interval, so params that
#: are genuinely live move together, while conditional PIDs that only appear
#: under certain running states still get a wide margin.
LATEST_VALUE_STALE_AFTER = timedelta(days=30)

#: Flips once telemetry_daily_summary.date reads as DATE, so the summary job
#: only inspects the column once per process. See summary_date_column_ready.
_summary_date_ready = False


class TelemetryQueriesMixin(TelemetryBase):
    """Latest values, ranges, stats, pruning and the daily summary job."""

    # =========================================================================
    # Query Methods
    # =========================================================================

    async def get_latest_values(self, vin: str) -> list[VehicleTelemetryLatest]:
        """Get the live telemetry values for a vehicle, excluding dead params.

        `vehicle_telemetry_latest` holds one row per (vin, param_key) and is
        never pruned (the daily job only prunes the historical table), so any
        param ever written under a VIN would otherwise render as a live gauge
        forever. A misattributed first ingest left a Mitsubishi drawing DPF,
        NOx, SCR and DEF cards from a diesel six months after the fact.

        Staleness is measured against the vehicle's OWN newest sample rather
        than wall-clock, so a vehicle parked for months keeps its full
        dashboard and only a param the rest of the vehicle has left behind
        drops off.
        """
        result = await self.db.execute(
            select(VehicleTelemetryLatest)
            .where(VehicleTelemetryLatest.vin == vin)
            .order_by(VehicleTelemetryLatest.param_key)
        )
        rows = list(result.scalars().all())
        if not rows:
            return []

        # The reference is the vehicle's newest sample, but never one dated in
        # the future: the WiCAN's optional device timestamp is not validated
        # against the clock, so a single dongle with a wrong date would push the
        # cutoff past every normally-dated parameter and blank the dashboard
        # until real time caught up.
        now = utc_now()
        plausible = [row.timestamp for row in rows if row.timestamp <= now]
        newest = max(plausible) if plausible else now
        cutoff = newest - LATEST_VALUE_STALE_AFTER
        return [row for row in rows if row.timestamp >= cutoff]

    async def get_telemetry_range(
        self,
        vin: str,
        start: datetime,
        end: datetime,
        param_keys: list[str] | None = None,
        limit: int = 10000,
    ) -> list[VehicleTelemetry]:
        """Query historical telemetry for a time range."""
        query = (
            select(VehicleTelemetry)
            .where(VehicleTelemetry.vin == vin)
            .where(VehicleTelemetry.timestamp >= start)
            .where(VehicleTelemetry.timestamp <= end)
        )

        if param_keys:
            query = query.where(VehicleTelemetry.param_key.in_(param_keys))

        query = query.order_by(VehicleTelemetry.timestamp).limit(limit)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_telemetry_stats(
        self,
        vin: str,
        param_key: str,
        start: datetime,
        end: datetime,
    ) -> dict[str, float | None]:
        """Get min/max/avg stats for a parameter in a time range."""
        result = await self.db.execute(
            select(
                func.min(VehicleTelemetry.value),
                func.max(VehicleTelemetry.value),
                func.avg(VehicleTelemetry.value),
                func.count(VehicleTelemetry.id),
            )
            .where(VehicleTelemetry.vin == vin)
            .where(VehicleTelemetry.param_key == param_key)
            .where(VehicleTelemetry.timestamp >= start)
            .where(VehicleTelemetry.timestamp <= end)
        )
        row = result.first()
        if not row:
            return {"min": None, "max": None, "avg": None, "count": 0}

        return {
            "min": row[0],
            "max": row[1],
            "avg": row[2],
            "count": row[3] or 0,
        }

    # =========================================================================
    # Retention / Cleanup
    # =========================================================================

    async def prune_old_telemetry(self, retention_days: int) -> int:
        """Delete telemetry older than retention period.

        Returns count of deleted rows.
        """
        cutoff = utc_now() - timedelta(days=retention_days)

        # The DELETE's own rowcount, not a count taken first: rows can land in between.
        result = await self.db.execute(
            delete(VehicleTelemetry).where(VehicleTelemetry.timestamp < cutoff)
        )
        await self.db.commit()
        deleted = cast(CursorResult[Any], result).rowcount or 0
        if deleted:
            logger.info("Pruned %d telemetry records older than %d days", deleted, retention_days)
        return deleted

    async def get_telemetry_row_count(self) -> int:
        """Get total row count for health monitoring."""
        result = await self.db.execute(select(func.count(VehicleTelemetry.id)))
        row = result.first()
        return row[0] if row else 0

    # =========================================================================
    # Daily Aggregation
    # =========================================================================

    async def summary_date_column_ready(self) -> bool:
        """Whether telemetry_daily_summary.date is a DATE column yet (migration 164).

        On the old SQLite DATETIME column a new ``2026-03-09`` key and an old
        ``2026-03-09 00:00:00`` one both pass the unique constraint, so writing
        before 164 lands would double every day. Logs and says no until then.
        """
        global _summary_date_ready
        if _summary_date_ready:
            return True
        conn = await self.db.connection()
        columns = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_columns("telemetry_daily_summary")
        )
        column_type = next((c["type"] for c in columns if c["name"] == "date"), None)
        # The old column reflects as DATETIME or TIMESTAMP, neither of which is a Date.
        if isinstance(column_type, Date):
            _summary_date_ready = True
            return True
        logger.error(
            "telemetry_daily_summary.date is %s, not DATE: migration 164 hasn't run, "
            "so daily summaries are skipped until it does",
            column_type,
        )
        return False

    async def generate_daily_summary(self, day: date, vin: str | None = None) -> int:
        """Generate summary aggregates for one household day.

        The window runs from local midnight to the next one, so a DST day is
        23 or 25 hours. Re-running a day updates its rows in place, and the
        day's rows end up being exactly what the window holds.

        Args:
            day: The household calendar day to aggregate
            vin: Optional specific VIN (None = all vehicles)

        Returns:
            Number of summary records created/updated, 0 when migration 164
            hasn't run yet
        """
        if not await self.summary_date_column_ready():
            return 0
        day_start, day_end = household_day_utc_bounds(day)

        # Build query for raw telemetry
        query = (
            select(
                VehicleTelemetry.vin,
                VehicleTelemetry.param_key,
                func.min(VehicleTelemetry.value),
                func.max(VehicleTelemetry.value),
                func.avg(VehicleTelemetry.value),
                func.count(VehicleTelemetry.id),
            )
            .where(VehicleTelemetry.timestamp >= day_start)
            .where(VehicleTelemetry.timestamp < day_end)
            .group_by(VehicleTelemetry.vin, VehicleTelemetry.param_key)
        )

        if vin:
            query = query.where(VehicleTelemetry.vin == vin)

        result = await self.db.execute(query)
        rows = result.fetchall()

        # A migrated UTC-day row can hold a key whose readings now sit on the
        # day before, so drop whatever this window no longer backs. Otherwise
        # those readings count twice (R1-H2).
        stale = delete(TelemetryDailySummary).where(TelemetryDailySummary.date == day)
        if vin:
            stale = stale.where(TelemetryDailySummary.vin == vin)
        if rows:
            stale = stale.where(
                tuple_(TelemetryDailySummary.vin, TelemetryDailySummary.param_key).not_in(
                    [(row[0], row[1]) for row in rows]
                )
            )
        await self.db.execute(stale)

        count = 0
        for row in rows:
            stmt = dialect_insert(TelemetryDailySummary).values(
                vin=row[0],
                param_key=row[1],
                date=day,
                min_value=row[2],
                max_value=row[3],
                avg_value=row[4],
                sample_count=row[5],
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["vin", "param_key", "date"],
                set_={
                    "min_value": row[2],
                    "max_value": row[3],
                    "avg_value": row[4],
                    "sample_count": row[5],
                },
            )
            await self.db.execute(stmt)
            count += 1

        await self.db.commit()
        return count

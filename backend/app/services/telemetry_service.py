"""Telemetry service for LiveLink data ingestion and storage.

The ingest core lives here; parameters, odometer, queries, alerts and the
session refresh queue live in app/services/telemetry/.
"""

import logging
import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import and_, or_, select
from sqlalchemy.engine import CursorResult

from app.database import is_sqlite
from app.services.livelink_sources.base import Reading, StoragePolicy
from app.utils.datetime_utils import utc_now

if is_sqlite:
    from sqlalchemy.dialects.sqlite import insert as dialect_insert
else:
    from sqlalchemy.dialects.postgresql import insert as dialect_insert

from app.models.drive_session import DriveSession
from app.models.livelink_device import LiveLinkDevice
from app.models.vehicle_telemetry import VehicleTelemetry, VehicleTelemetryLatest
from app.services.device_units import DeviceUnitService
from app.services.telemetry.alerts import TelemetryAlertsMixin
from app.services.telemetry.base import TelemetryBase

# Re-exported on purpose, so importing MaintenanceModeError from here keeps
# working after the split. The only name this module passes through.
from app.services.telemetry.helpers import MaintenanceModeError as MaintenanceModeError
from app.services.telemetry.helpers import (
    _delegates_to_store_telemetry,
    _refuse_if_in_maintenance,
)
from app.services.telemetry.odometer import TelemetryOdometerMixin
from app.services.telemetry.parameters import TelemetryParametersMixin
from app.services.telemetry.queries import TelemetryQueriesMixin
from app.services.telemetry.session_refresh import queue_session_refresh
from app.services.telemetry_validator import TelemetryValidator
from app.utils.autopid_normalizer import canonical_param_key, is_telemetry_param
from app.utils.logging_utils import sanitize_for_log
from app.utils.odometer_units import ODOMETER_UNIT_KM, odometer_value_to_km

#: How far a device-supplied sample timestamp may sit from its arrival time and
#: still count as "live" for the purpose of anchoring ``last_movement_at``.
#:
#: Matches the default contact-loss timeout, deliberately: a sample that is
#: further from now than the timeout that would have closed the session cannot
#: be describing the session that is open. Beyond this it's a replay, built into
#: closed sessions by sample time, and it never opens or holds the pointer.
LIVE_SAMPLE_TOLERANCE_SECONDS = 300

#: Devices already warned about a clock in the future, this process. A restart
#: warning again is a feature, same as `session_service._NO_MOVEMENT_WARNED`.
_FUTURE_CLOCK_WARNED: set[str] = set()


#: How far ahead of now a stored latest timestamp can be before it's a bad
#: clock to heal rather than a dongle a little fast (T4-e).
FUTURE_LATEST_SKEW = timedelta(minutes=5)


@dataclass
class StoreResult:
    """Result from store_telemetry() with stored count and validated data."""

    stored_count: int = 0
    validated_data: dict[str, float | int | str | None] = field(default_factory=dict)


logger = logging.getLogger(__name__)


class TelemetryService(
    TelemetryParametersMixin,
    TelemetryOdometerMixin,
    TelemetryQueriesMixin,
    TelemetryAlertsMixin,
    TelemetryBase,
):
    """Service for telemetry data ingestion and storage."""

    # =========================================================================
    # Telemetry Storage
    # =========================================================================

    async def store_telemetry(
        self,
        vin: str,
        device_id: str,
        autopid_data: dict[str, float | int | str | None],
        config: dict[str, dict[str, str | None]],
        timestamp: datetime | None = None,
    ) -> StoreResult:
        """Store telemetry data from a WiCAN payload.

        Args:
            vin: Vehicle VIN
            device_id: Device ID
            autopid_data: Parameter values from payload
            config: Parameter metadata from payload
            timestamp: Optional device timestamp (defaults to now)

        Returns:
            StoreResult with stored count and validated data
        """
        _refuse_if_in_maintenance("store_telemetry")
        if timestamp is None:
            timestamp = utc_now()

        # Canonicalize all keys to UPPERCASE with spaces→underscores so every ingest
        # path (MQTT, HTTPS, SD backfill) stores under the same param_key form, and
        # drop WiCAN frame-metadata params (TS, TIMESTAMP) that are not telemetry.
        # NaN and infinity go too. `ingest` already drops them; this keeps the
        # method safe on its own, since a NaN binds as NULL into the latest
        # table's NOT NULL on SQLite.
        autopid_data = {
            ck: v
            for ck, v in ((canonical_param_key(k), v) for k, v in autopid_data.items())
            if is_telemetry_param(ck) and (not isinstance(v, float) or math.isfinite(v))
        }

        # Normalise the odometer to canonical km ONCE, here, so every downstream
        # consumer (raw storage, the latest-value table, the odometer record and
        # the session stamp) reads the same units. Doing it per-consumer is what
        # let the record path and the storage path disagree for four months.
        declared_key = await self._declared_odometer_key(device_id)
        normalised = self._normalised_odometer_keys(autopid_data, declared_key, by_name=True)
        autopid_data = await self._normalize_odometer_units(
            device_id,
            autopid_data,
            normalised,
            {canonical_param_key(k): (c or {}).get("unit") for k, c in config.items()},
        )

        received_at = utc_now()

        # Get all parameters to check storage intervals and for validation
        parameters = await self.get_all_parameters()

        # Auto-register any new parameters before validation (so validator has class info)
        for param_key in autopid_data:
            if param_key not in parameters:
                param_config = config.get(param_key, {})
                unit = param_config.get("unit") if param_config else None
                param_class = param_config.get("class") if param_config else None
                # Converted above, so its row names km, not the unit it came in (FB-5).
                if param_key in normalised:
                    unit = ODOMETER_UNIT_KM
                param = await self.auto_register_parameter(param_key, unit, param_class)
                parameters[param_key] = param
            else:
                # Registered keys skip auto_register_parameter here, so the
                # rename runs on the rows we already hold (F6-1).
                self._adopt_readable_name(parameters[param_key])
        for param_key in normalised & autopid_data.keys():
            await self._label_odometer_km(parameters.get(param_key))

        # Validate telemetry values before storage
        validator = TelemetryValidator(self.db)
        valid_data, _rejected = await validator.validate_batch(
            vin, autopid_data, parameters, device_id=device_id, sample_at=timestamp
        )

        stored_count = 0
        #: Odometer readings the sanitizer threw out. They never reach a row, so
        #: they don't get to prove movement either (B6-12, I1).
        rejected_odometer: set[str] = set()

        for param_key, value in valid_data.items():
            if value is None:
                continue

            # Skip non-numeric values (e.g., DTC strings handled by route)
            if not isinstance(value, (int, float)):
                continue

            # Get parameter (already registered above)
            param = parameters.get(param_key)

            # Auto-register parameter if not exists
            param_config = config.get(param_key, {})
            param = parameters.get(param_key)
            if not param:
                unit = param_config.get("unit") if param_config else None
                param_class = param_config.get("class") if param_config else None
                param = await self.auto_register_parameter(param_key, unit, param_class)
                parameters[param_key] = param

            # Check if this is an odometer parameter and apply sanity checks
            # The declared key too: a custom odometer no pattern names gets the
            # same rounding and screening as the rest (OOS-2).
            is_odometer = self._is_odometer_param(param_key) or self._is_odometer_param(
                param_key, declared_key
            )
            if is_odometer:
                sanitized_value = await self._sanitize_odometer_value(vin, float(value))
                if sanitized_value is None:
                    # Invalid odometer value - skip storing to latest but may still log to historical
                    rejected_odometer.add(param_key)
                    continue
                value = sanitized_value

            # Update the live dashboard's value, unless this reading is older
            await self._upsert_latest_value(vin, param_key, float(value), timestamp, received_at)

            # Check storage interval for historical storage
            if param.storage_interval_seconds > 0:
                should_store = await self._should_store_historical(
                    vin, device_id, param_key, param.storage_interval_seconds, timestamp
                )
                if not should_store:
                    continue

            # Store to historical table. INSERT ... ON CONFLICT DO NOTHING on
            # the (device_id, param_key, timestamp) unique index, the same
            # dedup `bulk_backfill` and `store_readings` already use for this
            # table: a replayed duplicate is a routine outcome here,
            # not an exceptional one, and rowcount says whether the row
            # actually landed.
            stmt = (
                dialect_insert(VehicleTelemetry)
                .values(
                    vin=vin,
                    device_id=device_id,
                    param_key=param_key,
                    value=float(value),
                    timestamp=timestamp,
                    received_at=received_at,
                )
                .on_conflict_do_nothing(index_elements=["device_id", "param_key", "timestamp"])
            )
            result = await self.db.execute(stmt)
            stored_count += cast(CursorResult[Any], result).rowcount or 0

        # Decide what this batch means for the device's drive session.
        #
        # Here rather than at each caller, because there are THREE live ingest
        # sites -- MQTT `can/rx`, MQTT `can/status`, and the HTTPS payload route
        # -- and all three funnel through this method. An earlier design
        # revision hooked only the MQTT telemetry path, whose own comment
        # describes it as the FALLBACK for "WiCAN devices that don't send
        # explicit can/status messages": an instance whose dongle sends status
        # messages, or any instance on HTTPS ingest, would have kept 100% of its
        # phantom sessions while the changelog claimed otherwise.
        #
        # Reads `valid_data`, not the raw batch: the validator has already
        # dropped out-of-range garbage, and a spurious 400 km/h reading must not
        # be what opens a drive. Nor an odometer the sanitizer refused (an
        # overflow, a 16,000 km jump): it was never stored.
        observed = {k: v for k, v in valid_data.items() if k not in rejected_odometer}
        await self._observe_movement(vin, device_id, observed, timestamp, received_at)

        # Check for odometer reading and sync
        await self._sync_odometer_from_telemetry(vin, autopid_data, timestamp, declared_key)

        # A replayed reading can belong to a session that has already closed.
        await self._refresh_closed_session(vin, device_id, timestamp)

        return StoreResult(stored_count=stored_count, validated_data=valid_data)

    async def _observe_movement(
        self,
        vin: str,
        device_id: str,
        samples: dict[str, float | int | str | None],
        sample_at: datetime,
        received_at: datetime,
    ) -> None:
        """Feed one validated batch to the session state machine.

        ``sample_at`` is the device's own reading time and ``received_at`` is
        when it arrived here. The two are distinguished because they diverge:
        MQTT stamps ``utc_now()`` unconditionally, while the HTTPS route accepts
        an optional device timestamp that a buffering dongle sets hours in the
        past -- or, with a bad clock plugin, in the future.

        A sample far from receipt time is a replay. Since B6-12 it never opens
        or holds the pointed session and never anchors ``last_movement_at``,
        which every live timeout measures from; it is built into closed
        sessions from the rows already stored, unless it is the pointed
        session's own late sample.
        """
        from app.services.session_service import SessionService  # local import avoids cycle

        device = (
            await self.db.execute(
                select(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id)
            )
        ).scalar_one_or_none()
        if device is None:
            return

        sample = sample_at.replace(tzinfo=None) if sample_at.tzinfo else sample_at
        arrival = received_at.replace(tzinfo=None) if received_at.tzinfo else received_at
        live = abs((arrival - sample).total_seconds()) <= LIVE_SAMPLE_TOLERANCE_SECONDS
        ahead = (sample - arrival).total_seconds()
        if ahead > LIVE_SAMPLE_TOLERANCE_SECONDS and device.device_id not in _FUTURE_CLOCK_WARNED:
            # Once per device per process: every frame from that clock is in
            # the future, and the builder quietly drops what ends there (NB-2).
            _FUTURE_CLOCK_WARNED.add(device.device_id)
            logger.warning(
                "Device %s is stamping readings %d s in the future; its drives won't be "
                "recorded until the clock is fixed",
                sanitize_for_log(device.device_id),
                int(ahead),
            )

        await SessionService(self.db).observe_telemetry(device, samples, sample, live=live)

    async def _refresh_closed_session(self, vin: str, device_id: str, timestamp: datetime) -> None:
        """Recompute aggregates for a CLOSED session this reading falls inside.

        Off home WiFi a WiCAN buffers readings and replays them with their
        original timestamps, so telemetry keeps arriving after `end_session`
        has already computed a session's aggregates from the few samples that
        made it in live. On Diamond a drive recorded max_speed 20 km/h (the
        driveway) while the buffer it replayed 54 minutes later held 85 km/h.

        The session's own window is the arbiter, scoped by VIN. A reading that
        falls in the gap between sessions belongs to no session and is left
        alone: sessions end on device connectivity, so such readings are
        expected, and adopting one into the nearest session would invent a
        drive the vehicle did not make.

        Open sessions are excluded — `end_session` computes those on close.

        Queued behind the commit and debounced per session, not run here
        (B6-12, D-7): a replayed drive is closed from its second frame, so every
        later frame of the drain lands in its window, and recomputing it inline
        cost O(n) per frame.
        """
        # `_closed_sessions_in_span` below selects on `ended_at IS NOT NULL`.
        # `end_session` sets `ended_at` as a plain ORM attribute, no flush, so
        # a session this same unit of work already closed -- the HTTPS route
        # calling `handle_ecu_offline` (grace period 0) ahead of this same
        # payload's `store_telemetry`, both on one request's session -- is
        # invisible to that SELECT until something flushes it, and the very
        # readings that arrived alongside the close are excluded from the
        # session they just closed. `_open_session_for_movement` does not
        # need this: it flushes inside its own savepoint and only ever
        # creates an OPEN session, which this SELECT already excludes.
        # `refresh_aggregates` never reads `OdometerRecord` either, so an
        # odometer sync earlier in this batch is not a reason for this flush.
        await self.db.flush()

        reading_at = timestamp.replace(tzinfo=None) if timestamp.tzinfo else timestamp
        for session in await self._closed_sessions_in_span(vin, device_id, reading_at, reading_at):
            queue_session_refresh(self.db, session.id)

    async def _upsert_latest_value(
        self,
        vin: str,
        param_key: str,
        value: float,
        timestamp: datetime,
        received_at: datetime,
    ) -> None:
        """Upsert a value into the latest values cache table, unless it's older.

        A replayed reading lands after newer live ones, and overwriting would
        roll the dashboard back to it. An equal timestamp writes when the value
        differs (the later arrival wins the tie), but an exact duplicate leaves
        the row and its `received_at` alone (B6-7): a re-sent old reading isn't
        fresh. `_update_latest_if_newer` is the strict twin, for backfill.

        A stored row dated more than `FUTURE_LATEST_SKEW` after now is always
        overwritten. The device timestamp isn't checked against the clock, so
        one reading from a dongle with a bad clock would otherwise freeze this
        value until real time caught up (T4-a). A clock a minute or two fast
        isn't bad, and healing it let a replayed old reading displace the live
        value (T4-e).
        """
        stmt = dialect_insert(VehicleTelemetryLatest).values(
            vin=vin,
            param_key=param_key,
            value=value,
            timestamp=timestamp,
            received_at=received_at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["vin", "param_key"],
            set_={
                "value": stmt.excluded.value,
                "timestamp": stmt.excluded.timestamp,
                "received_at": stmt.excluded.received_at,
            },
            where=or_(
                VehicleTelemetryLatest.timestamp < stmt.excluded.timestamp,
                and_(
                    VehicleTelemetryLatest.timestamp == stmt.excluded.timestamp,
                    VehicleTelemetryLatest.value != stmt.excluded.value,
                ),
                VehicleTelemetryLatest.timestamp > utc_now() + FUTURE_LATEST_SKEW,
            ),
        )
        await self.db.execute(stmt)

    async def _should_store_historical(
        self,
        vin: str,
        device_id: str,
        param_key: str,
        interval_seconds: int,
        timestamp: datetime,
    ) -> bool:
        """Whether to keep this reading, given the parameter's storage interval.

        The interval thins a noisy parameter to at most one reading per window.
        It is measured against the READING's own timestamp, not the wall clock:
        a WiCAN off home WiFi replays its buffer with the original timestamps,
        so a reading taken at 10:48 can land at 11:42. Judged by arrival it sat
        moments behind the newest live row and a throttled parameter dropped
        it, after which the closed-session refresh recomputed from history that
        never received it and repaired nothing.

        Scoped to the device as well, so one dongle's cadence cannot thin
        another's readings on the same vehicle.
        """
        reading_at = timestamp.replace(tzinfo=None) if timestamp.tzinfo else timestamp
        window_start = reading_at - timedelta(seconds=interval_seconds)

        result = await self.db.execute(
            select(VehicleTelemetry.id)
            .where(VehicleTelemetry.vin == vin)
            .where(VehicleTelemetry.device_id == device_id)
            .where(VehicleTelemetry.param_key == param_key)
            .where(VehicleTelemetry.timestamp > window_start)
            .where(VehicleTelemetry.timestamp <= reading_at)
            .limit(1)
        )
        return result.first() is None

    # =========================================================================
    # SD-Card Bulk Backfill
    # =========================================================================

    async def bulk_backfill(self, vin: str, device_id: str, rows: list) -> int:
        """Insert historical SD-card rows without triggering live side-effects.

        rows: iterable of SdRow namedtuples with .param_key (already canonical),
        .value (float), .timestamp (datetime, tz-aware UTC).

        Deduplication is by (device_id, param_key, timestamp) — same unique
        constraint as the live ingest path.  Updates vehicle_telemetry_latest
        only when a backfilled row is strictly newer than the cached latest.

        Returns the number of rows actually inserted (conflict-skipped rows are
        not counted).
        """
        _refuse_if_in_maintenance("bulk_backfill")
        if not rows:
            return 0

        # Commit in batches so a large backfill (tens of thousands of SD rows) never
        # holds the SQLite write lock for the entire pull — live MQTT/HTTP ingest and
        # scheduler writes interleave between batches instead of hitting
        # "database is locked". Committed rows still dedup correctly across batches.
        commit_batch = 500
        inserted = 0
        stamps: list[datetime] = []
        observed: list[tuple[datetime, str, float]] = []

        # A NaN binds as NULL into a NOT NULL column. The parser drops them;
        # this keeps the method safe on its own, as store_telemetry is.
        rows = [r for r in rows if math.isfinite(r.value)]
        if not rows:
            return 0

        # The SD path writes straight to metric-canonical columns, so it
        # resolves units through the same step live ingest does (R12): stored
        # rows, mph to km/h, and the odometer order below. Otherwise one key
        # holds two scales depending on which path wrote it. A pull is one
        # device, so this is fetched once.
        resolved = await DeviceUnitService(self.db).resolve_readings(
            device_id, [Reading(r.param_key, r.value) for r in rows]
        )
        device_unit, device_kind = await self._odometer_units_for(device_id)
        declared = await self._declared_odometer_key(device_id)
        normalised = self._normalised_odometer_keys(
            {r.param_key for r in rows}, declared, by_name=True
        )
        # Records don't move during a pull, so the jump check's ceiling is read once.
        record_max: float | None = None

        for i, (r, reading) in enumerate(zip(rows, resolved, strict=True), start=1):
            # Normalise to naive UTC once so the (device_id, param_key, timestamp)
            # dedup index matches live-ingest rows (which store naive UTC via utc_now()).
            # Binding tz-aware datetimes into PG's TIMESTAMP WITHOUT TIME ZONE is also unsafe.
            ts = r.timestamp.replace(tzinfo=None) if r.timestamp.tzinfo is not None else r.timestamp

            value = reading.value
            if r.param_key in normalised:
                converted = odometer_value_to_km(
                    value, r.param_key, device_unit, device_kind, reading.unit
                )
                if converted is not None:
                    value = converted
            # Same rounding, cap and jump checks as live ingest, on the same
            # keys (B6-11), the declared one included. A dropped one is skipped
            # whole, as live drops it.
            if self._is_odometer_param(r.param_key) or self._is_odometer_param(
                r.param_key, declared
            ):
                if record_max is None:
                    record_max = await self._odometer_record_max(vin)
                sanitized = await self._sanitize_odometer_value(vin, value, record_max=record_max)
                if sanitized is None:
                    continue
                value = sanitized
            # Kept for the session reconstruction below, in CANONICAL km. The
            # predicate compares odometer readings against each other, so a
            # batch mixing raw miles with converted kilometres would see
            # increases and decreases that never happened.
            observed.append((ts, r.param_key, value))

            # Use the module-level dialect_insert (sqlite or pg, chosen at import time)
            stmt = (
                dialect_insert(VehicleTelemetry)
                .values(
                    vin=vin,
                    device_id=device_id,
                    param_key=r.param_key,
                    value=value,
                    timestamp=ts,
                )
                .on_conflict_do_nothing(index_elements=["device_id", "param_key", "timestamp"])
            )
            result = await self.db.execute(stmt)
            # rowcount is 1 on insert, 0 when the conflict clause fires
            row_inserted = cast(CursorResult[Any], result).rowcount or 0
            inserted += row_inserted
            await self._update_latest_if_newer(vin, r.param_key, value, ts)

            # Every parsed row widens the span, not just the ones that landed.
            # Narrowing it to new rows looked like free efficiency and is not:
            # the rows commit in batches here, while `SdBackfillService` saves
            # the file's watermark only after this returns, so a crash between
            # the two leaves the rows imported and their sessions never
            # recomputed. The retry re-parses the same rows, they all conflict,
            # and a span built from inserts would be empty -- losing the
            # refresh permanently. Parsing is already filtered by the watermark
            # (`SdLogParser.parse(since_ts=...)`), so in the ordinary case this
            # spans the new rows anyway; it only widens when the watermark did
            # not advance, which is exactly when the refresh needs redoing.
            stamps.append(ts)

            if i % commit_batch == 0:
                await self.db.commit()

        await self.db.commit()  # flush the final partial batch

        # Fold the batch into the sessions its rows fall inside. This path
        # deliberately skips `store_telemetry`, so it also skipped the
        # closed-session refresh that lives there -- which left the repair
        # covering the wrong path, because the SD card is where late data
        # actually comes from. Off home WiFi the WiCAN reaches no broker at
        # all, so a whole drive arrives here hours later.
        # Once per call, not once per row: running the live side-effects per
        # row is the thing `bulk_backfill` exists to avoid. Note the caller
        # loops over log files (`SdBackfillService._backfill`), so this is once
        # per file, not once per pull.
        if stamps:
            # Create the sessions these rows describe BEFORE refreshing, so a
            # newly created session is included in the refresh rather than
            # waiting for the next pull. This is the motivating case for the
            # whole boundary rework: `_refresh_sessions_in_span` selects
            # `ended_at IS NOT NULL`, i.e. sessions that already exist and are
            # already closed, so this path had never created one -- and it is
            # the only path for anything driven out of broker range.
            #
            # Once per call, not once per row: running the live side-effects per
            # row is precisely what `bulk_backfill` exists to avoid.
            await self._reconstruct_sessions_from_batch(vin, device_id, observed)
            await self._refresh_sessions_in_span(vin, device_id, min(stamps), max(stamps))
            await self.db.commit()

        return inserted

    async def _reconstruct_sessions_from_batch(
        self,
        vin: str,
        device_id: str,
        observed: list[tuple[datetime, str, float]],
    ) -> int:
        """Create or extend the drive sessions a replayed batch describes.

        The builder lives in `SessionService.reconstruct_sessions_from_rows`
        now (B6-12), since the HTTPS and MQTT replay paths use it too. This
        stays as the name `bulk_backfill` calls and tests patch.
        """
        from app.services.session_service import SessionService  # local: avoids a cycle

        return await SessionService(self.db).reconstruct_sessions_from_rows(
            vin, device_id, observed
        )

    async def _refresh_sessions_in_span(
        self, vin: str, device_id: str, start: datetime, end: datetime
    ) -> None:
        """Recompute every closed session of `vin` overlapping [start, end], now.

        Overlap only selects the candidates; each session then recomputes from
        its own window, so a session the pull merely straddles without landing
        any rows inside keeps the values it already had.

        SD backfill's refresh, once per batch. A single reading's goes through
        the debounced queue instead (`_refresh_closed_session`). Does not
        commit: callers own the transaction.

        Each one also gets a queued refresh behind the commit. The inline one
        doesn't take the session lock (it would wait on the lock while holding
        SQLite's), so a queued job could land after it with older figures. The
        follow-up reads under the lock after this commits, so it lands last.
        """
        from app.services.session_service import SessionService  # local import avoids cycle

        sessions = await self._closed_sessions_in_span(vin, device_id, start, end)
        if not sessions:
            return

        session_service = SessionService(self.db)
        for session in sessions:
            await session_service.refresh_aggregates(session)
            queue_session_refresh(self.db, session.id)

        logger.debug(
            "Refreshed %d closed session(s) for %s over %s..%s",
            len(sessions),
            vin[:8],
            sanitize_for_log(start),
            sanitize_for_log(end),
        )

    async def _closed_sessions_in_span(
        self, vin: str, device_id: str, start: datetime, end: datetime
    ) -> list[DriveSession]:
        """The closed sessions of this device and VIN overlapping [start, end]."""
        result = await self.db.execute(
            select(DriveSession)
            .where(DriveSession.vin == vin)
            # The reporting device, not just its VIN: two devices on one
            # vehicle have overlapping sessions, and each one's aggregates are
            # computed from its own telemetry.
            .where(DriveSession.device_id == device_id)
            .where(DriveSession.ended_at.is_not(None))
            .where(DriveSession.started_at <= end)
            .where(DriveSession.ended_at >= start)
        )
        return list(result.scalars().all())

    async def _update_latest_if_newer(
        self, vin: str, param_key: str, value: float, ts: datetime
    ) -> None:
        """Update vehicle_telemetry_latest only when ts is strictly newer.

        Never clobbers a fresher live reading with a backfilled historical row.
        VehicleTelemetryLatest has no device_id column -- do not pass one.
        Caller must pass ts as naive UTC (tzinfo=None).

        One atomic statement, not a SELECT then an ORM add. Production sessions
        do not autoflush, so the add was invisible to the next row's SELECT: an
        SD-card file carrying a param with no latest row yet added it twice and
        the chunk's commit failed on the unique key, which left the file's
        watermark unmoved and the device's SD backfill retrying that file
        forever. The conditional upsert also cannot race live ingest, and it
        holds no ORM object across `bulk_backfill`'s per-chunk commits.

        A stored row dated more than `FUTURE_LATEST_SKEW` after now loses to
        anything, same as `_upsert_latest_value`, so a bad device clock can't
        freeze it.
        """
        stmt = dialect_insert(VehicleTelemetryLatest).values(
            vin=vin,
            param_key=param_key,
            value=value,
            timestamp=ts,
            received_at=utc_now(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["vin", "param_key"],
            set_={
                "value": stmt.excluded.value,
                "timestamp": stmt.excluded.timestamp,
                "received_at": stmt.excluded.received_at,
            },
            where=or_(
                VehicleTelemetryLatest.timestamp < stmt.excluded.timestamp,
                VehicleTelemetryLatest.timestamp > utc_now() + FUTURE_LATEST_SKEW,
            ),
        )
        await self.db.execute(stmt)

    # =========================================================================
    # Simple Value Storage (for route compatibility)
    # =========================================================================

    async def store_readings(
        self,
        *,
        vin: str,
        device_id: str,
        readings: list[Reading],
        timestamp: datetime,
        policy: StoragePolicy,
        device: LiveLinkDevice | None = None,
    ) -> StoreResult:
        """Store normalized readings under a source's storage policy.

        The single storage entry point for `app.services.livelink_ingest`.
        Does NOT commit; the caller owns the transaction.

        When the policy asks for odometer sync or movement observation this
        delegates to `store_telemetry` UNCHANGED. That path also runs
        validation, odometer unit normalization and sanitization, movement
        observation and closed-session refresh. Reimplementing it here is how
        the port would silently lose behavior, so it does not.

        Only that delegating path runs `TelemetryValidator`. The simple path
        below stores every reading it is handed, so its `validated_data` is
        what was accepted, not what passed validation.
        """
        _refuse_if_in_maintenance("store_readings")
        if not readings:
            return StoreResult()

        # `device` carries `odometer_param_key`, which decides which odometer
        # the simple path below converts and records. None without the
        # ODOMETER capability.

        if _delegates_to_store_telemetry(policy):
            autopid: dict[str, float | int | str | None] = {r.param_key: r.value for r in readings}
            config: dict[str, dict[str, str | None]] = {
                r.param_key: {"unit": r.unit, "class": r.param_class}
                for r in readings
                if r.unit is not None or r.param_class is not None
            }
            return await self.store_telemetry(vin, device_id, autopid, config, timestamp)

        ts = timestamp.replace(tzinfo=None) if timestamp.tzinfo else timestamp

        # Normalise the odometer to canonical km ONCE, here, before any row is
        # written, exactly as store_telemetry does at its own entry point. Every
        # downstream consumer (the raw row, the latest-value table and the
        # odometer record) must read the same units; converting per-consumer is
        # what let the record path and the storage path disagree for four
        # months. `device` is None when the module lacks the ODOMETER
        # capability, so only `ODOMETER_MI` converts for a source with no
        # business recording an odometer: it's miles whoever sends it (R1-M1).
        declared = device.odometer_param_key if device else None
        normalised = self._normalised_odometer_keys(
            (r.param_key for r in readings), declared, by_name=False
        )
        if normalised:
            converted = await self._normalize_odometer_units(
                device_id,
                {r.param_key: r.value for r in readings},
                normalised,
                {r.param_key: r.unit for r in readings},
            )
            readings = [
                replace(r, value=float(value))
                if r.param_key in normalised and (value := converted.get(r.param_key)) is not None
                else r
                for r in readings
            ]

        stored = 0
        accepted: dict[str, float | int | str | None] = {}

        for reading in readings:
            odometer = reading.param_key in normalised
            param = await self.auto_register_parameter(
                reading.param_key,
                # Stored in km now, whatever unit it came in (FB-5).
                unit=ODOMETER_UNIT_KM if odometer else reading.unit,
                param_class=reading.param_class,
                display_name=reading.display_name,
            )
            if odometer:
                await self._label_odometer_km(param)
            accepted[reading.param_key] = reading.value

            if policy.latest == "if_newer":
                await self._update_latest_if_newer(vin, reading.param_key, reading.value, ts)
            else:
                await self._upsert_latest_value(
                    vin, reading.param_key, reading.value, ts, utc_now()
                )

            param = await self.get_parameter(reading.param_key)
            if param is not None and param.storage_interval_seconds > 0:
                keep = await self._should_store_historical(
                    vin,
                    device_id,
                    reading.param_key,
                    param.storage_interval_seconds,
                    ts,
                )
                if not keep:
                    continue

            stmt = (
                dialect_insert(VehicleTelemetry)
                .values(
                    vin=vin,
                    device_id=device_id,
                    param_key=reading.param_key,
                    value=float(reading.value),
                    timestamp=ts,
                )
                .on_conflict_do_nothing(index_elements=["device_id", "param_key", "timestamp"])
            )
            result = await self.db.execute(stmt)
            stored += cast(CursorResult[Any], result).rowcount or 0

        # Record the odometer for a source whose module does NOT already do it
        # inside store_telemetry. WiCAN returns above via the delegating branch,
        # so it cannot double-record.
        if declared:
            await self._sync_odometer_from_telemetry(vin, accepted, ts, declared)

        return StoreResult(stored_count=stored, validated_data=accepted)

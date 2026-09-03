"""Telemetry service for LiveLink data ingestion and storage."""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import is_sqlite
from app.utils.datetime_utils import utc_now

if is_sqlite:
    from sqlalchemy.dialects.sqlite import insert as dialect_insert
else:
    from sqlalchemy.dialects.postgresql import insert as dialect_insert

from app.models import OdometerRecord
from app.models.drive_session import DriveSession
from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_parameter import LiveLinkParameter
from app.models.vehicle_telemetry import (
    TelemetryDailySummary,
    VehicleTelemetry,
    VehicleTelemetryLatest,
)
from app.services.telemetry_validator import TelemetryValidator
from app.utils.autopid_normalizer import (
    canonical_param_key,
    infer_param_class,
    is_telemetry_param,
)
from app.utils.odometer_units import odometer_value_to_km


class MaintenanceModeError(RuntimeError):
    """Raised when a telemetry write is attempted during maintenance mode.

    The upgrade procedure for the odometer repair tools needs a window in which
    no new reading lands: a single reading arriving mid-repair recreates the
    mixed-unit state the tools refuse to run against.

    This lives on the writers rather than only on the routes because two rounds
    of review found an entry point the route gate did not cover -- first the
    admin SD backfill route, then `POST /api/livelink/mqtt/restart`, which
    writes nothing itself but starts the MQTT subscriber. MQTT is not a route,
    the scheduler is not a route, and the next ingest path need not be one
    either. Enumerating entry points is a floor; this is the choke point they
    all pass through.
    """


#: How far a device-supplied sample timestamp may sit from its arrival time and
#: still count as "live" for the purpose of anchoring ``last_movement_at``.
#:
#: Matches the default contact-loss timeout, deliberately: a sample that is
#: further from now than the timeout that would have closed the session cannot
#: be describing the session that is open. Beyond this the reading is treated as
#: replay -- still real driving, still allowed to open and extend a session, but
#: not allowed to move the anchor every live timeout measures from.
LIVE_SAMPLE_TOLERANCE_SECONDS = 300


def _refuse_if_in_maintenance(operation: str) -> None:
    """Raise if maintenance mode is on.

    Args:
        operation: Name of the write being attempted, for the log and message.

    Raises:
        MaintenanceModeError: If ``settings.maintenance_mode`` is set.
    """
    from app.config import settings

    if settings.maintenance_mode:
        logger.warning("Maintenance mode: refused %s", operation)
        raise MaintenanceModeError(
            f"{operation} refused: MyGarage is in maintenance mode and is not accepting telemetry."
        )


@dataclass
class StoreResult:
    """Result from store_telemetry() with stored count and validated data."""

    stored_count: int = 0
    validated_data: dict[str, float | int | str | None] = field(default_factory=dict)


# PIDs that represent odometer readings (case-insensitive matching)
ODOMETER_PID_PATTERNS = [
    "A6-",  # Standard OBD2 PID 0xA6 (166)
    "ODOMETER",
    "ODO",
    "MILEAGE",
    "DISTANCE_TOTAL",
    "TOTAL_DISTANCE",
]

#: How far a param's newest sample may trail the vehicle's newest sample before
#: it stops counting as live. Generous on purpose: every reported param is
#: upserted on every payload regardless of its storage interval, so params that
#: are genuinely live move together, while conditional PIDs that only appear
#: under certain running states still get a wide margin.
LATEST_VALUE_STALE_AFTER = timedelta(days=30)

logger = logging.getLogger(__name__)


class TelemetryService:
    """Service for telemetry data ingestion and storage."""

    def __init__(self, db: AsyncSession):
        """Initialize with database session."""
        self.db = db

    # =========================================================================
    # Payload Hash / Deduplication
    # =========================================================================

    @staticmethod
    def compute_payload_hash(autopid_data: dict[str, Any]) -> str:
        """Compute a hash of the autopid_data for deduplication.

        Uses sorted JSON serialization to ensure consistent hashing.
        """
        # Sort keys and round floats for consistent hashing
        normalized = {}
        for key, value in sorted(autopid_data.items()):
            if isinstance(value, float):
                # Round to 2 decimal places to handle float precision
                normalized[key] = round(value, 2)
            else:
                normalized[key] = value

        serialized = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode()).hexdigest()[:16]  # First 16 chars

    async def is_duplicate_payload(self, device_id: str, payload_hash: str) -> bool:
        """Check if payload is a duplicate based on hash.

        Returns True if the hash matches the device's last_payload_hash.
        """
        result = await self.db.execute(
            select(LiveLinkDevice.last_payload_hash).where(LiveLinkDevice.device_id == device_id)
        )
        row = result.first()
        if not row or not row[0]:
            return False

        return row[0] == payload_hash

    async def update_payload_hash(self, device_id: str, payload_hash: str) -> None:
        """Update the device's last_payload_hash."""
        await self.db.execute(
            text(
                "UPDATE livelink_devices SET last_payload_hash = :hash WHERE device_id = :device_id"
            ).bindparams(hash=payload_hash, device_id=device_id)
        )

    # =========================================================================
    # Parameter Management
    # =========================================================================

    async def get_parameter(self, param_key: str) -> LiveLinkParameter | None:
        """Get a parameter by key."""
        result = await self.db.execute(
            select(LiveLinkParameter).where(LiveLinkParameter.param_key == param_key)
        )
        return result.scalar_one_or_none()

    async def get_all_parameters(self) -> dict[str, LiveLinkParameter]:
        """Get all parameters as a dict keyed by param_key."""
        result = await self.db.execute(select(LiveLinkParameter))
        return {p.param_key: p for p in result.scalars().all()}

    async def get_or_create_parameter(
        self,
        param_key: str,
        display_name: str | None = None,
        unit: str | None = None,
        param_class: str | None = None,
    ) -> LiveLinkParameter | None:
        """Get or create a parameter definition.

        Wrapper for auto_register_parameter for route compatibility.
        """
        return await self.auto_register_parameter(param_key, unit, param_class)

    async def auto_register_parameter(
        self,
        param_key: str,
        unit: str | None = None,
        param_class: str | None = None,
    ) -> LiveLinkParameter:
        """Auto-register a new parameter from WiCAN config block.

        Returns existing parameter if already registered.
        """
        # Explicit config class always wins; otherwise fall back to the
        # conservative catalog inference so MQTT-discovered params (which
        # arrive with an empty config block) still get validator range/rate
        # coverage. NOTE: the catalog matches on short substrings (e.g.
        # PRES, TEMP) and a future PID could false-positive (e.g. a
        # hypothetical COMPRESSOR key contains PRES) — extend
        # `_PARAM_CLASS_PATTERNS` conservatively.
        resolved_class = param_class or infer_param_class(param_key)

        existing = await self.get_parameter(param_key)
        if existing:
            # Update metadata if provided and not already set
            if unit and not existing.unit:
                existing.unit = unit
            if not existing.param_class and resolved_class:
                existing.param_class = resolved_class
                # Only recompute category when it's unset or still the
                # "other" default — category is user-editable in the admin
                # UI, and a hand-tuned value must survive the class backfill.
                if not existing.category or existing.category == "other":
                    existing.category = self._classify_param(resolved_class)
            return existing

        # Create new parameter
        category = self._classify_param(resolved_class)
        display_name = self._format_display_name(param_key)

        # Set sensible defaults based on the resolved class. Only applied to
        # brand-new rows — existing rows keep whatever show_on_dashboard/
        # archive_only a user has hand-tuned in the admin UI.
        show_on_dashboard = resolved_class in (
            "speed",
            "frequency",
            "temperature",
            "voltage",
            "battery",
        )
        archive_only = not show_on_dashboard

        param = LiveLinkParameter(
            param_key=param_key,
            display_name=display_name,
            unit=unit,
            param_class=resolved_class,
            category=category,
            show_on_dashboard=show_on_dashboard,
            archive_only=archive_only,
            storage_interval_seconds=0,  # Store all by default
        )
        self.db.add(param)
        await self.db.flush()

        logger.info("Auto-registered new parameter: %s", param_key)
        return param

    def _classify_param(self, param_class: str | None) -> str:
        """Classify a parameter into a category based on its class."""
        if not param_class:
            return "other"

        class_lower = param_class.lower()
        if class_lower in ("temperature",):
            return "temperature"
        elif class_lower in ("speed", "distance"):
            return "engine"
        elif class_lower in ("frequency",):  # RPM
            return "engine"
        elif class_lower in ("voltage", "battery"):
            return "electrical"
        elif class_lower in ("pressure", "vacuum"):
            return "engine"
        elif class_lower in ("power_factor",):  # Throttle, load
            return "engine"
        else:
            return "other"

    def _format_display_name(self, param_key: str) -> str:
        """Format a parameter key into a display name."""
        # Replace underscores with spaces and title case
        return param_key.replace("_", " ").title()

    def _is_odometer_param(self, param_key: str) -> bool:
        """Check if a parameter key represents an odometer reading."""
        param_upper = param_key.upper()
        for pattern in ODOMETER_PID_PATTERNS:
            if pattern.upper() in param_upper:
                return True
        return False

    async def _odometer_units_for(self, device_id: str) -> tuple[str | None, str | None]:
        """Return the device's declared `(odometer_unit, kind)`, or `(None, None)`."""
        row = (
            await self.db.execute(
                select(LiveLinkDevice.odometer_unit, LiveLinkDevice.kind).where(
                    LiveLinkDevice.device_id == device_id
                )
            )
        ).first()
        return row if row else (None, None)

    async def _normalize_odometer_units(
        self,
        device_id: str,
        autopid_data: dict[str, float | int | str | None],
    ) -> dict[str, float | int | str | None]:
        """Return ``autopid_data`` with any odometer value converted to km.

        Only the standard SAE J1979 PID is guaranteed metric; a bare autopid key
        is a user-defined CAN expression and is usually miles on a US-market
        car. The device's declared `odometer_unit` decides, falling back to the
        key shape (WiCAN only) when it has not been set.
        """
        if not any(self._is_odometer_param(k) for k in autopid_data):
            return autopid_data

        device_unit, device_kind = await self._odometer_units_for(device_id)

        normalized = dict(autopid_data)
        for param_key, value in autopid_data.items():
            if value is None or not self._is_odometer_param(param_key):
                continue
            try:
                converted = odometer_value_to_km(float(value), param_key, device_unit, device_kind)
            except TypeError, ValueError:
                continue
            if converted is not None:
                normalized[param_key] = converted
        return normalized

    async def _sanitize_odometer_value(self, vin: str, value: float) -> float | None:
        """Sanitize an odometer value (km), returning None if invalid.

        Applies the same sanity checks as _sync_odometer_from_telemetry:
        - Absolute cap at ~1.6 million km (1M mi equivalent)
        - Reject unreasonable jumps (>16,000 km from existing max)
        - Reject negative/zero values

        Returns:
            Sanitized value if valid, None if should be rejected
        """
        odometer_km = int(round(value))

        # Reject zero/negative
        if odometer_km <= 0:
            return None

        # Absolute cap at ~1.6M km (no vehicle reaches this)
        if odometer_km > 1_600_000:
            logger.warning(
                "Rejected odometer %d km for %s: exceeds 1.6M km cap",
                odometer_km,
                vin[:8],
            )
            return None

        # Query max existing odometer_km to check for unreasonable jumps
        max_result = await self.db.execute(
            select(func.max(OdometerRecord.odometer_km)).where(OdometerRecord.vin == vin)
        )
        max_odometer_km = max_result.scalar() or 0

        # Reject values that are unreasonably higher than existing max
        # (prevents overflow values like 0xFFFFFF from being displayed)
        if max_odometer_km > 0 and odometer_km > float(max_odometer_km) + 16_000:
            logger.warning(
                "Rejected odometer %d km for %s: unreasonable jump from %s",
                odometer_km,
                vin[:8],
                max_odometer_km,
            )
            return None

        return float(odometer_km)

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
        autopid_data = {
            ck: v
            for ck, v in ((canonical_param_key(k), v) for k, v in autopid_data.items())
            if is_telemetry_param(ck)
        }

        # Normalise the odometer to canonical km ONCE, here, so every downstream
        # consumer (raw storage, the latest-value table, the odometer record and
        # the session stamp) reads the same units. Doing it per-consumer is what
        # let the record path and the storage path disagree for four months.
        autopid_data = await self._normalize_odometer_units(device_id, autopid_data)

        received_at = utc_now()

        # Get all parameters to check storage intervals and for validation
        parameters = await self.get_all_parameters()

        # Auto-register any new parameters before validation (so validator has class info)
        for param_key in autopid_data:
            if param_key not in parameters:
                param_config = config.get(param_key, {})
                unit = param_config.get("unit") if param_config else None
                param_class = param_config.get("class") if param_config else None
                param = await self.auto_register_parameter(param_key, unit, param_class)
                parameters[param_key] = param

        # Validate telemetry values before storage
        validator = TelemetryValidator(self.db)
        valid_data, _rejected = await validator.validate_batch(vin, autopid_data, parameters)

        stored_count = 0

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
            is_odometer = self._is_odometer_param(param_key)
            if is_odometer:
                sanitized_value = await self._sanitize_odometer_value(vin, float(value))
                if sanitized_value is None:
                    # Invalid odometer value - skip storing to latest but may still log to historical
                    continue
                value = sanitized_value

            # Always update latest value (for live dashboard)
            await self._upsert_latest_value(vin, param_key, float(value), timestamp, received_at)

            # Check storage interval for historical storage
            if param.storage_interval_seconds > 0:
                should_store = await self._should_store_historical(
                    vin, device_id, param_key, param.storage_interval_seconds, timestamp
                )
                if not should_store:
                    continue

            # Store to historical table
            try:
                telemetry = VehicleTelemetry(
                    vin=vin,
                    device_id=device_id,
                    param_key=param_key,
                    value=float(value),
                    timestamp=timestamp,
                    received_at=received_at,
                )
                self.db.add(telemetry)
                stored_count += 1
            except IntegrityError:
                # Duplicate (same device_id, param_key, timestamp) - skip
                pass

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
        # be what opens a drive.
        await self._observe_movement(vin, device_id, valid_data, timestamp, received_at)

        # Check for odometer reading and sync
        await self._sync_odometer_from_telemetry(vin, autopid_data, timestamp)

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

        A sample far from receipt time may still open and extend a session (it
        is real driving that happened), but must not anchor
        ``last_movement_at``, which every live timeout measures from. Anchoring
        a live session on a replayed timestamp drags it hours away from where it
        belongs and makes the contact-loss clock fire against a moment the
        device never spoke.
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
        """
        reading_at = timestamp.replace(tzinfo=None) if timestamp.tzinfo else timestamp
        await self._refresh_sessions_in_span(vin, device_id, reading_at, reading_at)

    async def _sync_odometer_from_telemetry(
        self,
        vin: str,
        autopid_data: dict[str, float | int | str | None],
        timestamp: datetime,
    ) -> None:
        """Sync odometer record from telemetry if odometer PID is present.

        Only creates one record per day to avoid spamming the odometer table.
        Records are marked with source='livelink'.
        """
        # Find odometer value in telemetry
        odometer_value: float | None = None
        odometer_key: str | None = None

        for param_key, value in autopid_data.items():
            if value is None:
                continue

            # Check if this is an odometer parameter
            param_upper = param_key.upper()
            for pattern in ODOMETER_PID_PATTERNS:
                if pattern.upper() in param_upper:
                    odometer_value = float(value)
                    odometer_key = param_key
                    break
            if odometer_value is not None:
                break

        if odometer_value is None or odometer_key is None:
            return  # No odometer PID found

        # Already canonical km: store_telemetry normalised the whole payload
        # through _normalize_odometer_units before any consumer saw it.
        odometer_km = int(round(odometer_value))
        if odometer_km <= 0:
            return  # Invalid odometer reading

        # Sanity check: absolute cap at ~1.6M km (no vehicle reaches this)
        if odometer_km > 1_600_000:
            logger.warning(
                "Rejected odometer %d km for %s: exceeds 1.6M km cap",
                odometer_km,
                vin[:8],
            )
            return

        # Query max existing odometer_km for this VIN to avoid duplicate values
        max_result = await self.db.execute(
            select(func.max(OdometerRecord.odometer_km)).where(OdometerRecord.vin == vin)
        )
        max_odometer_km = max_result.scalar() or 0

        # Sanity check: reject unreasonable jumps (prevents overflow values like 0xFFFFFF)
        if max_odometer_km > 0 and odometer_km > float(max_odometer_km) + 16_000:
            logger.warning(
                "Rejected odometer %d km for %s: unreasonable jump from %s",
                odometer_km,
                vin[:8],
                max_odometer_km,
            )
            return

        # Only proceed if this is a new higher reading.
        # Logged because a units mismatch makes every reading look backwards, and
        # a silent return here hid exactly that for four months (see 6f04e53).
        if odometer_km <= float(max_odometer_km):
            logger.debug(
                "Skipped odometer %d km for %s (%s): not above existing max %s",
                odometer_km,
                vin[:8],
                odometer_key,
                max_odometer_km,
            )
            return

        # Cap date to today (don't allow future dates from device clock issues)
        today = date_type.today()
        record_date = min(timestamp.date(), today) if timestamp else today

        result = await self.db.execute(
            select(OdometerRecord).where(
                OdometerRecord.vin == vin,
                OdometerRecord.date == record_date,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Only update if this is a LiveLink record (don't overwrite manual entries)
            if existing.source == "livelink":
                existing.odometer_km = odometer_km
                existing.notes = f"Auto-updated from LiveLink ({odometer_key})"
            # else: manual entry, don't overwrite
        else:
            # Create new odometer record
            odometer_record = OdometerRecord(
                vin=vin,
                date=record_date,
                odometer_km=odometer_km,
                source="livelink",
                notes=f"Auto-recorded from LiveLink ({odometer_key})",
            )
            self.db.add(odometer_record)
            logger.info(
                "Created odometer record for %s: %d km from %s",
                vin[:8],
                odometer_km,
                odometer_key,
            )

    async def _upsert_latest_value(
        self,
        vin: str,
        param_key: str,
        value: float,
        timestamp: datetime,
        received_at: datetime,
    ) -> None:
        """Upsert a value into the latest values cache table."""
        # Use SQLite's INSERT OR REPLACE
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
                "value": value,
                "timestamp": timestamp,
                "received_at": received_at,
            },
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

        # The SD path writes `r.value` straight to a metric-canonical column,
        # so it needs the same odometer conversion `store_telemetry` applies:
        # a bare `ODOMETER` autopid on a US-market car reports miles. Fetched
        # once here rather than per row; a pull is one device.
        device_unit, device_kind = await self._odometer_units_for(device_id)

        for i, r in enumerate(rows, start=1):
            # Normalise to naive UTC once so the (device_id, param_key, timestamp)
            # dedup index matches live-ingest rows (which store naive UTC via utc_now()).
            # Binding tz-aware datetimes into PG's TIMESTAMP WITHOUT TIME ZONE is also unsafe.
            ts = r.timestamp.replace(tzinfo=None) if r.timestamp.tzinfo is not None else r.timestamp

            value = r.value
            if self._is_odometer_param(r.param_key):
                converted = odometer_value_to_km(value, r.param_key, device_unit, device_kind)
                if converted is not None:
                    value = converted

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
            row_inserted = result.rowcount or 0
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
            await self._refresh_sessions_in_span(vin, device_id, min(stamps), max(stamps))
            await self.db.commit()

        return inserted

    async def _refresh_sessions_in_span(
        self, vin: str, device_id: str, start: datetime, end: datetime
    ) -> None:
        """Recompute every closed session of `vin` overlapping [start, end].

        Overlap only selects the candidates; each session then recomputes from
        its own window, so a session the pull merely straddles without landing
        any rows inside keeps the values it already had.

        The single point a closed session is refreshed from ingest: a live
        reading is the degenerate span `[ts, ts]`. Does not commit: callers
        own the transaction, and `store_telemetry` deliberately does not.
        """
        from app.services.session_service import SessionService  # local import avoids cycle

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
        sessions = list(result.scalars().all())
        if not sessions:
            return

        session_service = SessionService(self.db)
        for session in sessions:
            await session_service.refresh_aggregates(session)

        logger.debug(
            "Refreshed %d closed session(s) for %s over %s..%s",
            len(sessions),
            vin[:8],
            start,
            end,
        )

    async def store_torque_telemetry(
        self, vin: str, device_id: str, timestamp: datetime, values: dict[str, float]
    ) -> int:
        """Idempotently store Torque OBD readings (all at one timestamp).

        Auto-registers unknown params, dedups on (device_id, param_key, timestamp)
        via on_conflict_do_nothing, and keeps vehicle_telemetry_latest current.
        Does NOT commit — the caller owns the transaction. `values` keys are already
        canonical param_keys (see torque_pid_map). `timestamp` must be naive UTC.
        """
        _refuse_if_in_maintenance("store_torque_telemetry")
        if not values:
            return 0
        ts = timestamp.replace(tzinfo=None) if timestamp.tzinfo is not None else timestamp
        inserted = 0
        for param_key, value in values.items():
            await self.auto_register_parameter(param_key)
            stmt = (
                dialect_insert(VehicleTelemetry)
                .values(
                    vin=vin,
                    device_id=device_id,
                    param_key=param_key,
                    value=float(value),
                    timestamp=ts,
                )
                .on_conflict_do_nothing(index_elements=["device_id", "param_key", "timestamp"])
            )
            result = await self.db.execute(stmt)
            inserted += result.rowcount or 0
            await self._update_latest_if_newer(vin, param_key, float(value), ts)
        return inserted

    async def _update_latest_if_newer(
        self, vin: str, param_key: str, value: float, ts: datetime
    ) -> None:
        """Update vehicle_telemetry_latest only when ts is strictly newer.

        Never clobbers a fresher live reading with a backfilled historical row.
        VehicleTelemetryLatest has no device_id column — do not pass one.
        Caller must pass ts as naive UTC (tzinfo=None).
        """
        existing = (
            await self.db.execute(
                select(VehicleTelemetryLatest).where(
                    VehicleTelemetryLatest.vin == vin,
                    VehicleTelemetryLatest.param_key == param_key,
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            self.db.add(
                VehicleTelemetryLatest(
                    vin=vin,
                    param_key=param_key,
                    value=value,
                    timestamp=ts,
                    received_at=utc_now(),
                )
            )
        elif ts > existing.timestamp:
            existing.value = value
            existing.timestamp = ts
            existing.received_at = utc_now()

    # =========================================================================
    # Query Methods
    # =========================================================================

    async def get_latest_values(self, vin: str) -> list[VehicleTelemetryLatest]:
        """Get the live telemetry values for a vehicle, excluding dead params.

        `vehicle_telemetry_latest` holds one row per (vin, param_key) and is
        never pruned — the daily job only prunes the historical table — so any
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
        now = utc_now().replace(tzinfo=None)
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

        # Count first for logging
        count_result = await self.db.execute(
            select(func.count(VehicleTelemetry.id)).where(VehicleTelemetry.timestamp < cutoff)
        )
        count_row = count_result.first()
        to_delete = count_row[0] if count_row else 0

        if to_delete > 0:
            await self.db.execute(
                delete(VehicleTelemetry).where(VehicleTelemetry.timestamp < cutoff)
            )
            await self.db.commit()
            logger.info("Pruned %d telemetry records older than %d days", to_delete, retention_days)

        return to_delete

    async def get_telemetry_row_count(self) -> int:
        """Get total row count for health monitoring."""
        result = await self.db.execute(select(func.count(VehicleTelemetry.id)))
        row = result.first()
        return row[0] if row else 0

    # =========================================================================
    # Daily Aggregation
    # =========================================================================

    async def generate_daily_summary(self, date: datetime, vin: str | None = None) -> int:
        """Generate daily summary aggregates for a specific date.

        Args:
            date: The date to aggregate (uses midnight UTC)
            vin: Optional specific VIN (None = all vehicles)

        Returns:
            Number of summary records created/updated
        """
        # Normalize to midnight UTC
        day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

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

        count = 0
        for row in rows:
            stmt = dialect_insert(TelemetryDailySummary).values(
                vin=row[0],
                param_key=row[1],
                date=day_start,
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

    # =========================================================================
    # Simple Value Storage (for route compatibility)
    # =========================================================================

    async def store_value(
        self,
        vin: str,
        device_id: str,
        param_key: str,
        value: float,
    ) -> bool:
        """Store a single telemetry value.

        Returns True if stored to historical table, False if skipped due to interval.
        Always updates the latest value cache.
        """
        timestamp = utc_now()
        received_at = timestamp

        # Get parameter for storage interval check
        param = await self.get_parameter(param_key)

        # Always update latest value
        await self._upsert_latest_value(vin, param_key, value, timestamp, received_at)

        # Check storage interval
        if param and param.storage_interval_seconds > 0:
            should_store = await self._should_store_historical(
                vin, param_key, param.storage_interval_seconds
            )
            if not should_store:
                return False

        # Store to historical table
        try:
            telemetry = VehicleTelemetry(
                vin=vin,
                device_id=device_id,
                param_key=param_key,
                value=value,
                timestamp=timestamp,
                received_at=received_at,
            )
            self.db.add(telemetry)
            return True
        except IntegrityError:
            return False

    async def check_thresholds(
        self,
        vin: str,
        param_key: str,
        value: float,
    ) -> None:
        """Check if a value exceeds parameter thresholds and send notifications.

        Respects alert cooldown to prevent notification spam.
        """
        param = await self.get_parameter(param_key)
        if not param:
            return

        # Check if value is outside thresholds
        alert_type = None
        threshold_value = None

        if param.warning_max is not None and value > param.warning_max:
            alert_type = "max"
            threshold_value = param.warning_max
        elif param.warning_min is not None and value < param.warning_min:
            alert_type = "min"
            threshold_value = param.warning_min

        if not alert_type or threshold_value is None:
            return

        # Cooldown - skip dispatch while a prior notification for this
        # parameter is still within the admin-configured cooldown window
        # (Settings -> LiveLink, `livelink_alert_cooldown_minutes`, default
        # 30). WiCAN can emit several breaching frames a minute; without
        # this every one would dispatch. Thresholds live on the param (not
        # per-vehicle), so the cooldown is global-per-param. The setting is
        # only read once a prior stamp exists — first-ever breaches skip
        # the extra settings query.
        now = utc_now()
        if param.warning_last_notified_at is not None:
            from app.services.livelink_service import LiveLinkService

            cooldown_minutes = await LiveLinkService(self.db).get_alert_cooldown_minutes()
            if now - param.warning_last_notified_at < timedelta(minutes=cooldown_minutes):
                return

        # Get vehicle name for notification
        from app.models.vehicle import Vehicle

        result = await self.db.execute(
            select(Vehicle.year, Vehicle.make, Vehicle.model).where(Vehicle.vin == vin)
        )
        row = result.first()
        if row:
            vehicle_name = f"{row[0]} {row[1]} {row[2]}"
        else:
            vehicle_name = f"Vehicle ({vin[:8]}...)"

        # Send notification
        from app.services.notifications.dispatcher import NotificationDispatcher

        dispatcher = NotificationDispatcher(self.db)
        dispatch_results = await dispatcher.notify_livelink_threshold_alert(
            vehicle_name=vehicle_name,
            parameter_name=param.display_name or param_key,
            value=value,
            threshold_type=alert_type,
            threshold_value=threshold_value,
            unit=param.unit,
        )

        # Stamp the cooldown only when at least one service actually accepted
        # the notification. The dispatcher records False for attempted-but-
        # failed sends, so an all-failed dict (e.g. transient outage) must not
        # start the cooldown clock and silence real alerts; nor must an empty
        # dict (event disabled / no services enabled). The caller commits the
        # surrounding transaction, so no explicit commit here.
        if any(dispatch_results.values()):
            param.warning_last_notified_at = now

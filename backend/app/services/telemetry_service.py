"""Telemetry service for LiveLink data ingestion and storage."""

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Any, cast

from sqlalchemy import and_, delete, func, not_, or_, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import is_sqlite
from app.services.livelink_sources.base import Reading, StoragePolicy
from app.services.session_boundaries import DriveWindow
from app.utils.datetime_utils import utc_now

if is_sqlite:
    from sqlalchemy.dialects.sqlite import insert as dialect_insert
else:
    from sqlalchemy.dialects.postgresql import insert as dialect_insert

from app.models import OdometerRecord
from app.models.drive_session import DriveSession
from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_parameter import DISPLAY_NAME_MAX_LENGTH, LiveLinkParameter
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
from app.utils.household_time import household_today
from app.utils.logging_utils import sanitize_for_log
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

#: VIN -> date of the last "declared odometer never records" warning. Bounded by
#: the number of vehicles, which is a household's worth, so it never needs
#: eviction.
_DECLARED_ODOMETER_WARNED: dict[str, date] = {}


class TelemetryService:
    """Service for telemetry data ingestion and storage."""

    def __init__(self, db: AsyncSession):
        """Initialize with database session."""
        self.db = db

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
        return await self.auto_register_parameter(param_key, unit, param_class, display_name)

    async def fill_declared_units(self, units: Mapping[str, str]) -> None:
        """Give rows that exist and have no unit the one a source declared.

        Creates nothing: a parameter is registered when its first value arrives,
        with the unit app/services/declared_units.py kept for it.
        """
        _refuse_if_in_maintenance("fill_declared_units")
        rows = await self.db.execute(
            select(LiveLinkParameter).where(LiveLinkParameter.param_key.in_(list(units)))
        )
        for param in rows.scalars():
            if not param.unit:
                param.unit = units[param.param_key]

    async def auto_register_parameter(
        self,
        param_key: str,
        unit: str | None = None,
        param_class: str | None = None,
        display_name: str | None = None,
    ) -> LiveLinkParameter:
        """Auto-register a new parameter from WiCAN config block.

        Returns existing parameter if already registered.

        A source's `display_name` names a new row, and an existing one still on
        its auto name; a name someone set stays. It is cut to the column's
        width: PostgreSQL refuses a longer one where SQLite stores it (TQ-L2).
        """
        if display_name is not None:
            display_name = display_name[:DISPLAY_NAME_MAX_LENGTH]
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
            if display_name and existing.display_name in (
                None,
                self._format_display_name(param_key),
            ):
                existing.display_name = display_name
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
        display_name = display_name or self._format_display_name(param_key)

        # Defaults for brand-new rows only; existing rows keep whatever a user
        # has set.
        #
        # Every new parameter starts on the dashboard. The Live tab has always
        # drawn every reading, and hiding one is now an explicit per-reading
        # switch in the integrations settings, not a class default nobody chose
        # (migration 114 reset the rows this used to decide).
        #
        # The class list governs only archive_only, which keeps a parameter out
        # of the chart picker. It predates config-driven sources, when every
        # class came from a WiCAN config block, so a new source whose headline
        # reading has a new class is unchartable by default. That is what
        # happened to the Mopeka preset until `propane` was added.
        chartable = resolved_class in (
            "speed",
            "frequency",
            "temperature",
            "voltage",
            "battery",
            "propane",
        )
        show_on_dashboard = True
        archive_only = not chartable

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

    @staticmethod
    def _format_display_name(param_key: str) -> str:
        """Format a parameter key into a display name.

        Also the test for "still the auto name" when a source names a reading
        (auto_register_parameter), so the two can't drift.
        """
        # Replace underscores with spaces and title case
        return param_key.replace("_", " ").title()

    def _is_odometer_param(self, param_key: str, declared: str | None = None) -> bool:
        """Check if a parameter key represents an odometer reading.

        ``declared`` is the device's ``odometer_param_key``. When set it
        REPLACES the pattern scan for that one key, so a device can name a
        parameter no pattern would match (a vendor custom PID, say) without
        widening the match for anything else.
        """
        if declared:
            return param_key.upper() == declared.upper()
        param_upper = param_key.upper()
        for pattern in ODOMETER_PID_PATTERNS:
            if pattern.upper() in param_upper:
                return True
        return False

    async def _declared_odometer_key(self, device_id: str) -> str | None:
        """The device's `odometer_param_key`, or None when it declares nothing.

        NULL is the default and the reason existing installs are unaffected:
        every predicate falls back to its usual name matching.
        """
        row = await self.db.execute(
            select(LiveLinkDevice.odometer_param_key).where(LiveLinkDevice.device_id == device_id)
        )
        return row.scalar_one_or_none()

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
        declared: str | None = None,
    ) -> dict[str, float | int | str | None]:
        """Return ``autopid_data`` with any odometer value converted to km.

        Only the standard SAE J1979 PID is guaranteed metric; a bare autopid key
        is a user-defined CAN expression and is usually miles on a US-market
        car. The device's declared `odometer_unit` decides, falling back to the
        key shape (WiCAN only) when it has not been set.
        """
        if not any(self._is_odometer_param(k, declared) for k in autopid_data):
            return autopid_data

        device_unit, device_kind = await self._odometer_units_for(device_id)

        normalized = dict(autopid_data)
        for param_key, value in autopid_data.items():
            if value is None or not self._is_odometer_param(param_key, declared):
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
        autopid_data = await self._normalize_odometer_units(device_id, autopid_data, declared_key)

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
        valid_data, _rejected = await validator.validate_batch(
            vin, autopid_data, parameters, sample_at=timestamp
        )

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
        # be what opens a drive.
        await self._observe_movement(vin, device_id, valid_data, timestamp, received_at)

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
        # `_refresh_sessions_in_span` below selects on `ended_at IS NOT NULL`.
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
        await self._refresh_sessions_in_span(vin, device_id, reading_at, reading_at)

    async def _sync_odometer_from_telemetry(
        self,
        vin: str,
        autopid_data: dict[str, float | int | str | None],
        timestamp: datetime,
        declared: str | None = None,
    ) -> None:
        """Sync odometer record from telemetry if odometer PID is present.

        Keeps at most one LiveLink record per day, to avoid spamming the
        odometer table, marked with source='livelink'. It updates that record
        or creates it beside the day's other readings, and never modifies a
        record of another source.
        """
        # Find odometer value in telemetry
        odometer_value: float | None = None
        odometer_key: str | None = None

        for param_key, value in autopid_data.items():
            if value is None:
                continue

            # Was an inline copy of the pattern scan. It has to go through the
            # predicate, or a device's declaration never reaches this path and a
            # declared key that matches no pattern records nothing, silently.
            if self._is_odometer_param(param_key, declared):
                odometer_value = float(value)
                odometer_key = param_key
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
            if declared:
                # A DECLARED odometer that never records is the expected steady
                # state for an app-accumulated total that drifts low (Torque's
                # ff120C) once any fuel record sits above it. Debug is too quiet
                # for that: the feature would produce nothing and say nothing.
                #
                # Throttled to once per VIN per day. Torque uploads every few
                # seconds, so an unthrottled warning is ~1,800 lines per
                # half-hour drive. Module-level because TelemetryService is
                # constructed per request, so instance state would never survive
                # to throttle anything.
                today_utc = utc_now().date()
                if _DECLARED_ODOMETER_WARNED.get(vin) != today_utc:
                    _DECLARED_ODOMETER_WARNED[vin] = today_utc
                    logger.warning(
                        "Declared odometer %s for %s read %d km, at or below the "
                        "existing maximum %s. No record written. If this repeats, "
                        "the declared parameter may be a trip counter or an "
                        "app-accumulated total rather than the vehicle odometer.",
                        odometer_key,
                        vin[:8],
                        odometer_km,
                        max_odometer_km,
                    )
            else:
                logger.debug(
                    "Skipped odometer %d km for %s (%s): not above existing max %s",
                    odometer_km,
                    vin[:8],
                    odometer_key,
                    max_odometer_km,
                )
            return

        # Cap date to today (don't allow future dates from device clock issues)
        today = household_today()
        record_date = min(timestamp.date(), today) if timestamp else today

        # LiveLink owns only its own rows. A day can hold several odometer rows
        # (a service visit and the tire mount it did, a tread reading above
        # this device's earlier one), so "the" row of the day is not a thing to
        # look up: asking for exactly one raised on every odometer-bearing
        # message of such a day and rolled the whole message back. The day's
        # own LiveLink row is updated; otherwise one is created beside whatever
        # the day holds, and no other source's row is ever modified. The guard
        # above admits only a reading above every stored one, so a created row
        # is always the day's highest.
        result = await self.db.execute(
            select(OdometerRecord)
            .where(
                OdometerRecord.vin == vin,
                OdometerRecord.date == record_date,
                OdometerRecord.source == "livelink",
            )
            .order_by(OdometerRecord.id.desc())
        )
        existing = result.scalars().first()

        if existing is not None:
            existing.odometer_km = odometer_km
            existing.notes = f"Auto-updated from LiveLink ({odometer_key})"
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
        """Upsert a value into the latest values cache table, unless it's older.

        A replayed reading lands after newer live ones, and overwriting would
        roll the dashboard back to it. An equal timestamp still writes, so a
        re-sent reading refreshes `received_at`. `_update_latest_if_newer` is
        the strict twin, for backfill.

        A stored row dated after now is always overwritten. The device
        timestamp isn't checked against the clock, so one reading from a dongle
        with a bad clock would otherwise freeze this value until real time
        caught up (T4-a).
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
                VehicleTelemetryLatest.timestamp <= stmt.excluded.timestamp,
                VehicleTelemetryLatest.timestamp > utc_now(),
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

        Returns the number of sessions created or extended.

        The grouping is `session_boundaries.group_drives`, which applies the
        same movement predicate and the same gap as the live path -- so a drive
        is cut the same way whether it arrived over MQTT or off an SD card.

        Three rules keep this from making things worse than the bug it fixes:

        - **Torque sessions are never touched.** The phone supplies an
          authoritative session id; re-bounding it on a gap threshold replaces
          good evidence with inference. Excluded by `external_session_id`, not
          by heuristic.
        - **No overlaps are written.** Nothing in the schema forbids them, and
          every aggregate is a window scan, so two overlapping sessions both
          claim the same samples and both report the same distance.
        - **An ambiguous window is left alone.** A drive overlapping more than
          one existing session is a history-repair problem, not a backfill one;
          merging them here would be a destructive guess made during an ingest.
        - **An open session keeps its end** (R10). It's still running, so it
          matches any drive that ends after it started. A drive that started
          earlier backdates its start (clamped past the device's last close);
          the end stays the live path's.
        """
        from app.services.session_boundaries import BOUNDARY_ALGORITHM_MOVEMENT, group_drives

        device = (
            await self.db.execute(
                select(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id)
            )
        ).scalar_one_or_none()
        if device is None or not device.vin:
            return 0

        from app.services.livelink_service import LiveLinkService  # local: avoids a cycle

        gap = await LiveLinkService(self.db).get_session_gap_minutes()
        drives = group_drives(observed, gap)
        if not drives:
            return 0

        changed = 0
        for index, drive in enumerate(drives):
            # Inclusive at both bounds by default: a session matches this drive
            # when each one's start is at or before the other's end, and an
            # open session has no end yet, so it reaches past any drive. A
            # single-instant touch with a session from the live path or from
            # another SD file is most plausibly the same physical drive seen by
            # two sources (a device reconnecting mid-drive, or one reading both
            # logged to SD and sent over HTTPS), so it matches.
            #
            # The two exclusions below apply only at an instant this drive
            # shares with the adjacent drive of this same `group_drives` call,
            # which gives that instant to the earlier drive. The ownership is a
            # property of one call, where both drives were cut from the same
            # evidence; it says nothing about a session from anywhere else.
            # Neither exclusion can remove a genuine overlap (a positive shared
            # duration), because both require the two windows to meet at
            # exactly one point.
            conditions = [
                DriveSession.device_id == device_id,
                DriveSession.external_session_id.is_(None),
                DriveSession.started_at <= drive.movement_ended_at,
                or_(DriveSession.ended_at.is_(None), DriveSession.ended_at >= drive.started_at),
            ]

            if index + 1 < len(drives) and drives[index + 1].started_at == drive.movement_ended_at:
                # Right: the next drive in this batch starts exactly at this
                # drive's movement_ended_at, which is always this drive's own
                # movement sample. A session that starts there and runs on past
                # it is the next drive's. An open session starting there counts
                # as running on past it, since it is still going. A closed
                # session that starts and ends at that instant keeps matching
                # this drive.
                conditions.append(
                    not_(
                        and_(
                            DriveSession.started_at == drive.movement_ended_at,
                            or_(
                                DriveSession.ended_at.is_(None),
                                DriveSession.ended_at > drive.movement_ended_at,
                            ),
                        )
                    )
                )

            if index > 0 and drives[index - 1].movement_ended_at == drive.started_at:
                # Left: the previous drive in this batch ends exactly at this
                # drive's started_at, so a closed session ending there is the
                # previous drive's. Closed sessions only: an open session is
                # still running past this instant, so it keeps matching and the
                # open-session branch below handles it. The IS NOT NULL is what
                # keeps it: NOT (NULL = x) is NULL, which drops the row.
                conditions.append(
                    not_(
                        and_(
                            DriveSession.ended_at.is_not(None),
                            DriveSession.ended_at == drive.started_at,
                        )
                    )
                )

            overlapping = list(
                (await self.db.execute(select(DriveSession).where(*conditions))).scalars().all()
            )

            if len(overlapping) > 1:
                logger.info(
                    "SD reconstruction: drive %s..%s for %s spans %d existing sessions; "
                    "left unchanged (history repair, not ingest)",
                    drive.started_at,
                    drive.movement_ended_at,
                    sanitize_for_log(device_id),
                    len(overlapping),
                )
                continue

            if overlapping:
                session = overlapping[0]
                if session.ended_at is None:
                    # An OPEN session is the live path's business: it is still
                    # deciding where this drive ends, and closing it here would
                    # race the timeout clocks. Its start is fair game, though:
                    # WiFi came back mid-drive and the card holds the head.
                    if await self._backdate_open_session(session, drive):
                        changed += 1
                    continue
                session.started_at = min(self._naive_ts(session.started_at), drive.started_at)
                session.ended_at = max(self._naive_ts(session.ended_at), drive.movement_ended_at)
                session.movement_started_at = min(
                    self._naive_ts(session.movement_started_at) or drive.movement_started_at,
                    drive.movement_started_at,
                )
                session.movement_ended_at = max(
                    self._naive_ts(session.movement_ended_at) or drive.movement_ended_at,
                    drive.movement_ended_at,
                )
            else:
                session = DriveSession(
                    vin=device.vin,
                    device_id=device_id,
                    started_at=drive.started_at,
                    ended_at=drive.movement_ended_at,
                    movement_started_at=drive.movement_started_at,
                    movement_ended_at=drive.movement_ended_at,
                    boundary_algorithm_version=BOUNDARY_ALGORITHM_MOVEMENT,
                    effective_gap_minutes=gap,
                )
                self.db.add(session)
                # Flushed (not just added), not committed: production sessions
                # are autoflush=False, so without this the next drive's own
                # overlap query -- issued in the same loop, same transaction --
                # cannot see a session this loop just created. A commit stays
                # the caller's: bulk_backfill commits once after every drive
                # in the batch is done.
                await self.db.flush()
                logger.info(
                    "SD reconstruction: created session for %s over %s..%s",
                    sanitize_for_log(device_id),
                    drive.started_at,
                    drive.movement_ended_at,
                )

            # Read back into locals and narrow. Both were assigned non-None a
            # few lines up, in either branch, but they are nullable columns and
            # a later edit to one branch could stop being true without anything
            # here noticing.
            window_start = self._naive_ts(session.started_at)
            window_end = self._naive_ts(session.ended_at)
            if window_start is not None and window_end is not None:
                session.duration_seconds = max(0, int((window_end - window_start).total_seconds()))
            changed += 1

        await self.db.flush()
        return changed

    async def _backdate_open_session(self, session: DriveSession, drive: DriveWindow) -> bool:
        """Pull an open session's start back to an SD drive that began first (R10).

        Clamped past the device's last close the same way a live open is, and
        only ever earlier. A session the drive started inside of is left be.
        Returns True when the start moved.
        """
        from app.services.session_service import SessionService  # local: avoids a cycle

        current_start = self._naive_ts(session.started_at)
        if current_start is None or drive.started_at >= current_start:
            return False
        started_at, movement_started_at, _ = await SessionService(
            self.db
        ).clamp_past_previous_close(
            session.device_id,
            drive.started_at,
            drive.movement_started_at,
            drive.movement_ended_at,
        )
        if started_at >= current_start:
            return False
        session.started_at = started_at
        # A contact-mode session has no movement record; don't invent one.
        current_movement = self._naive_ts(session.movement_started_at)
        if current_movement is not None:
            session.movement_started_at = min(current_movement, movement_started_at)
        logger.info(
            "SD reconstruction: backdated open session %d for %s from %s to %s",
            session.id,
            sanitize_for_log(session.device_id),
            current_start,
            started_at,
        )
        return True

    @staticmethod
    def _naive_ts(value: datetime | None) -> datetime | None:
        return value.replace(tzinfo=None) if value is not None and value.tzinfo else value

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
            sanitize_for_log(start),
            sanitize_for_log(end),
        )

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

        A stored row dated after now loses to anything, same as
        `_upsert_latest_value`, so a bad device clock can't freeze it.
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
                VehicleTelemetryLatest.timestamp > utc_now(),
            ),
        )
        await self.db.execute(stmt)

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

        # `device` is optional here and REQUIRED by Task 17: it carries
        # `odometer_param_key`, which decides whether an odometer normalisation
        # step runs before any row is written. Task 17 adds that step; leave the
        # parameter unused for now rather than changing the signature twice.

        if policy.sync_odometer or policy.observe_movement:
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
        # capability, so this is dead for a source that has no business
        # recording one.
        declared = device.odometer_param_key if device else None
        if declared:
            normalised = await self._normalize_odometer_units(
                device_id, {r.param_key: r.value for r in readings}, declared
            )
            readings = [
                replace(r, value=float(normalised[r.param_key]))
                if normalised.get(r.param_key) is not None
                else r
                for r in readings
            ]

        stored = 0
        accepted: dict[str, float | int | str | None] = {}

        for reading in readings:
            await self.auto_register_parameter(
                reading.param_key,
                unit=reading.unit,
                param_class=reading.param_class,
                display_name=reading.display_name,
            )
            accepted[reading.param_key] = reading.value

            if policy.latest == "if_newer":
                await self._update_latest_if_newer(vin, reading.param_key, reading.value, ts)
            else:
                await self._upsert_latest_value(
                    vin, reading.param_key, reading.value, ts, utc_now()
                )

            if policy.apply_storage_interval:
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

    async def check_thresholds(
        self,
        vin: str,
        param_key: str,
        value: float,
        *,
        once: bool = False,
        odometer_normalised: bool = False,
        declared_odometer_key: str | None = None,
    ) -> None:
        """Notify when a value crosses one of its parameter's alert lines.

        `once`: notify once per crossing (`alert_state`, see `livelink_alerts`),
        as a preset sensor's readings do. Otherwise every breaching reading
        notifies again, held back by the alert cooldown.

        `odometer_normalised`: the source runs odometer normalisation (it has
        `Capability.ODOMETER`), so an odometer key, by the same match
        normalisation used (`declared_odometer_key` is the device's
        `odometer_param_key`), holds km. The alert then reads in the owner's
        distance unit whatever the parameter row's unit says.
        """
        from app.services.livelink_alerts import alert_band, alert_quantity, band_line, crossing

        param = await self.get_parameter(param_key)
        if not param:
            return

        now = utc_now()
        if once:
            # Held, or re-armed by a value back clear of its line: the state
            # is stored as is. A band to notify leaves it unchanged.
            band, param.alert_state = crossing(param.alert_state, value, param)
            if band is None:
                return
            # A send no service accepted is tried again once the cooldown has
            # passed, not on every reading: a tank sits below its line for
            # days, and each send to a service that is down retries inline.
            if param.alert_retry_at is not None and now < param.alert_retry_at:
                return
        else:
            band = alert_band(value, param)
            if band is None:
                return
            # Same hold as above (R2): without it a webhook outage retried
            # inline on every breaching frame, and stalled MQTT ingest.
            if param.alert_retry_at is not None and now < param.alert_retry_at:
                return

        from app.services.livelink_service import LiveLinkService

        livelink = LiveLinkService(self.db)

        # Cooldown - skip dispatch while a prior notification for this
        # parameter is still within the admin-configured cooldown window
        # (Settings -> LiveLink, `livelink_alert_cooldown_minutes`, default
        # 30). WiCAN can emit several breaching frames a minute; without
        # this every one would dispatch. Thresholds live on the param (not
        # per-vehicle), so the cooldown is global-per-param. The setting is
        # only read once a prior stamp exists — first-ever breaches skip
        # the extra settings query. A notify-once reading has no cooldown:
        # it notifies each band once, whenever it enters it.
        if not once and param.warning_last_notified_at is not None:
            cooldown_minutes = await livelink.get_alert_cooldown_minutes()
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

        # Lines are canonical metric, so the alert reads in the owner's units,
        # but only for a value known to be canonical. A custom key whose row
        # says psi holds psi, and prints as it is (D2a).
        from app.utils.render_context import render_context_for_vehicle

        quantity = alert_quantity(
            param.param_class,
            param.unit,
            odometer_normalised=odometer_normalised
            and self._is_odometer_param(param_key, declared_odometer_key),
        )

        # Send notification
        from app.services.notifications.dispatcher import NotificationDispatcher

        dispatcher = NotificationDispatcher(self.db)
        dispatch_results = await dispatcher.notify_livelink_threshold_alert(
            vehicle_name=vehicle_name,
            parameter_name=param.display_name or param_key,
            value=value,
            band=band,
            threshold_value=band_line(band, param),
            unit=param.unit,
            ctx=await render_context_for_vehicle(self.db, vin),
            quantity=quantity,
        )

        # Stamp the cooldown, and a notify-once reading's band, only when at
        # least one service actually accepted the notification. The
        # dispatcher records False for attempted-but-failed sends, so an
        # all-failed dict (e.g. transient outage) must not start the cooldown
        # clock and silence real alerts; nor must an empty dict (event
        # disabled / no services enabled). Either way a send nothing took
        # waits one cooldown before it's tried again. The caller commits the
        # surrounding transaction, so no explicit commit here.
        if any(dispatch_results.values()):
            param.warning_last_notified_at = now
            param.alert_retry_at = None
            if once:
                param.alert_state = band
        else:
            cooldown_minutes = await livelink.get_alert_cooldown_minutes()
            param.alert_retry_at = now + timedelta(minutes=cooldown_minutes)

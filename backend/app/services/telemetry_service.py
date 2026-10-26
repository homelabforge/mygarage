"""Telemetry service for LiveLink data ingestion and storage."""

import asyncio
import logging
import math
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from functools import partial
from typing import Any, cast

from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.database import is_sqlite
from app.services.livelink_sources.base import Reading, StoragePolicy
from app.utils.datetime_utils import utc_now

if is_sqlite:
    from sqlalchemy.dialects.sqlite import insert as dialect_insert
else:
    from sqlalchemy.dialects.postgresql import insert as dialect_insert

from app.models import OdometerRecord
from app.models.drive_session import DriveSession
from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_parameter import DISPLAY_NAME_MAX_LENGTH, LiveLinkParameter
from app.models.livelink_topic_map import LiveLinkTopicMap
from app.models.vehicle_telemetry import (
    TelemetryDailySummary,
    VehicleTelemetry,
    VehicleTelemetryLatest,
)
from app.services.device_units import DeviceUnitService, relabel_parameter
from app.services.livelink_alerts import ThresholdAlert, deliver_threshold_alert
from app.services.post_commit import after_commit
from app.services.telemetry_validator import TelemetryValidator
from app.utils.autopid_normalizer import (
    canonical_param_key,
    infer_param_class,
    is_telemetry_param,
)
from app.utils.household_time import household_today
from app.utils.logging_utils import sanitize_for_log
from app.utils.odometer_units import (
    ODOMETER_UNIT_KM,
    WICAN_DEVICE_KIND,
    is_converted_odometer_key,
    is_miles_odometer_key,
    is_miles_unit,
    odometer_value_to_km,
    stores_odometer_key_raw,
)


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


#: How far ahead of now a stored latest timestamp can be before it's a bad
#: clock to heal rather than a dongle a little fast (T4-e).
FUTURE_LATEST_SKEW = timedelta(minutes=5)


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


def _delegates_to_store_telemetry(policy: StoragePolicy) -> bool:
    """Whether `store_readings` hands this policy's batch to `store_telemetry`."""
    return policy.sync_odometer or policy.observe_movement


def normalises_odometer(policy: StoragePolicy, device: LiveLinkDevice | None) -> bool:
    """Whether `store_readings` converts a batch's odometer to km.

    `device` is what the caller passes `store_readings` (None without the
    ODOMETER capability). `store_telemetry` converts every odometer key by the
    device's match (its declared key, else name matching); the simple path
    only a declared one. Torque has ODOMETER and still converts nothing
    without a declared key, so the capability alone doesn't say. `ODOMETER_MI`
    is converted on every path, and `check_thresholds` knows that per key.
    """
    if _delegates_to_store_telemetry(policy):
        return True
    return device is not None and bool(device.odometer_param_key)


#: A closed session a replay keeps landing in isn't recomputed per frame. The
#: refresh runs behind the commit, this long after the last frame that asked
#: for it, and no later than this long after the first (B6-12, D-7). The test
#: suite sets both to 0.
SESSION_REFRESH_DEBOUNCE_SECONDS = 2.0
SESSION_REFRESH_MAX_DELAY_SECONDS = 30.0


@dataclass
class _RefreshDue:
    first: float
    deadline: float


#: Session id -> the refresh job already waiting on it. Written by the JOB when
#: it starts, never when it's queued, so a transaction that rolls back after
#: queueing leaves nothing behind to suppress the next one (E-3).
_REFRESH_DUE: dict[int, _RefreshDue] = {}


def queue_session_refresh(db: AsyncSession, session_id: int) -> None:
    """Recompute a closed session's aggregates once ``db`` commits, debounced per session."""
    after_commit(
        db, partial(_refresh_session_debounced, session_id), label=f"refresh-session:{session_id}"
    )


async def _refresh_session_debounced(session_id: int, db: AsyncSession) -> None:
    """The queued job: the first one for a session waits out the debounce, the rest push it."""
    now = time.monotonic()
    due = _REFRESH_DUE.get(session_id)
    if due is not None:
        # Another job is already waiting: push its deadline and go.
        due.deadline = min(
            now + SESSION_REFRESH_DEBOUNCE_SECONDS, due.first + SESSION_REFRESH_MAX_DELAY_SECONDS
        )
        return
    due = _RefreshDue(first=now, deadline=now + SESSION_REFRESH_DEBOUNCE_SECONDS)
    _REFRESH_DUE[session_id] = due
    try:
        while (remaining := due.deadline - time.monotonic()) > 0:
            await asyncio.sleep(remaining)
    except asyncio.CancelledError:
        # Shutdown mid-sleep (`post_commit.shutdown`): refresh once now rather
        # than lose the drain's last seconds to a restart (E-12). The runner
        # won't commit after a cancellation, so commit here.
        _REFRESH_DUE.pop(session_id, None)
        await _refresh_session_now(db, session_id)
        await db.commit()
        raise
    _REFRESH_DUE.pop(session_id, None)
    await _refresh_session_now(db, session_id)


async def _refresh_session_now(db: AsyncSession, session_id: int) -> None:
    """Recompute one closed session, if it's still there and still closed."""
    from app.services.session_service import SessionService  # local import avoids cycle

    session = await db.get(DriveSession, session_id)
    if session is None or session.ended_at is None:
        return  # merged away, or reopened: nothing to recompute
    await SessionService(db).refresh_aggregates(session)


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
        widening the match for anything else. The scan is
        `is_converted_odometer_key`'s, shared with the old-reading guard.
        """
        return is_converted_odometer_key(param_key, declared)

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

    def _normalised_odometer_keys(
        self, keys: Iterable[str], declared: str | None, *, by_name: bool
    ) -> set[str]:
        """The keys a storage path converts to km.

        `by_name`: `store_telemetry` converts every odometer key by the
        device's match (`declared` replaces the name scan); the simple path
        only a declared one. `ODOMETER_MI` is miles for every kind, so it's
        converted on both (Codex R1-M1).
        """
        return {
            k
            for k in keys
            if is_miles_odometer_key(k)
            or ((by_name or declared) and self._is_odometer_param(k, declared))
        }

    async def _normalize_odometer_units(
        self,
        device_id: str,
        autopid_data: dict[str, float | int | str | None],
        keys: set[str],
        key_units: Mapping[str, str | None] | None = None,
    ) -> dict[str, float | int | str | None]:
        """Return ``autopid_data`` with each odometer in ``keys`` converted to km.

        ``key_units`` is each key's unit as it arrived (this request's
        `config`). It goes through R12's resolution with the device's stored
        rows, so a kept `legacy` row and a boot declaration both reach this.
        `resolve_odometer_unit` has the order: device unit, then that, then
        the key shape (WiCAN only).
        """
        # Values narrowed here, so the loop below needs no None check.
        odometers = {k: v for k, v in autopid_data.items() if v is not None and k in keys}
        if not odometers:
            return autopid_data

        device_unit, device_kind = await self._odometer_units_for(device_id)
        given = key_units or {}
        units = await DeviceUnitService(self.db).resolve_key_units(
            device_id, {k: given.get(k) for k in odometers}
        )

        normalized = dict(autopid_data)
        for param_key, value in odometers.items():
            try:
                converted = odometer_value_to_km(
                    float(value), param_key, device_unit, device_kind, units.get(param_key)
                )
            except TypeError, ValueError:
                continue
            if converted is not None:
                normalized[param_key] = converted
        return normalized

    async def _label_odometer_km(self, param: LiveLinkParameter | None) -> None:
        """A normalised odometer's row says km, whatever an older version wrote (FB-5).

        R4 relabels an mph row the same way. An empty unit gets km too: the
        browser reads an odometer's unit from this row, not its name
        (FW-A-r3). The lines stay: they were always compared with the stored
        values, which were km.

        Rows are global by key, so a key another device stores raw (another
        kind that doesn't declare it, or a WiCAN that declares a different
        key) keeps its label, as migration 133 leaves it (FW-A-r4b). That
        check is a query, so it only runs while the row still needs relabelling.
        """
        if param is None:
            return
        unlabelled = not (param.unit or "").strip()
        if not (unlabelled or is_miles_unit(param.unit)):
            return
        if await self._another_device_stores_raw(param.param_key):
            return
        relabel_parameter(param, ODOMETER_UNIT_KM)

    async def _another_device_stores_raw(self, param_key: str) -> bool:
        """Whether a device that doesn't convert ``param_key`` may have sent it.

        Migration 133's guard for its km stamp, asked live. Every device that
        may have sent the key, judged by `stores_odometer_key_raw`. Raw rows
        alone aren't enough (wave A re-review T2): they prune at 90 days, and a
        deleted device's stay behind under an id that's no longer on file. So
        the evidence is, as in 133:

        - a device on file with raw rows under the key;
        - a device on file with a topic map that sends it the key (generic
          MQTT: that's where its keys come from, and it doesn't prune);
        - a WiCAN on file whose vehicle has a latest row for the key, when it's
          the only device that has reported on that vehicle: linked, or with a
          drive there (a WiCAN names its own autopids, so its vehicle's latest
          rows are the record that outlives the raw ones, but they're the
          vehicle's, not the device's, so with company they prove nothing,
          wave B review M-4);
        - raw rows under the key from a device that's gone. Its kind is
          unknown, so they count as raw, until they prune.

        Torque needs none of these: its keys come from its own fixed map, and
        none of them is an odometer a WiCAN records.
        """
        other = aliased(LiveLinkDevice)
        sent_it = or_(
            exists().where(
                VehicleTelemetry.device_id == LiveLinkDevice.device_id,
                VehicleTelemetry.param_key == param_key,
            ),
            exists().where(
                LiveLinkTopicMap.device_id == LiveLinkDevice.device_id,
                LiveLinkTopicMap.param_key == param_key,
            ),
            and_(
                LiveLinkDevice.kind == WICAN_DEVICE_KIND,
                exists().where(
                    VehicleTelemetryLatest.vin == LiveLinkDevice.vin,
                    VehicleTelemetryLatest.param_key == param_key,
                ),
                ~exists().where(
                    other.vin == LiveLinkDevice.vin, other.device_id != LiveLinkDevice.device_id
                ),
                ~exists().where(
                    DriveSession.vin == LiveLinkDevice.vin,
                    DriveSession.device_id != LiveLinkDevice.device_id,
                ),
            ),
        )
        rows = await self.db.execute(
            select(LiveLinkDevice.kind, LiveLinkDevice.odometer_param_key).where(sent_it)
        )
        if any(stores_odometer_key_raw(param_key, kind, declared) for kind, declared in rows.all()):
            return True
        if not stores_odometer_key_raw(param_key, None):
            return False  # every kind converts it (ODOMETER_MI)
        return await self._a_gone_device_sent(param_key)

    async def _a_gone_device_sent(self, param_key: str) -> bool:
        """Whether a device no longer on file has raw rows under ``param_key``.

        Walks the distinct device ids in the raw table one index seek at a time
        (a handful of devices, ever), the way migration 133 walks a device's keys.
        """
        on_file = set((await self.db.execute(select(LiveLinkDevice.device_id))).scalars().all())
        previous = ""
        while True:
            device_id = await self.db.scalar(
                select(func.min(VehicleTelemetry.device_id)).where(
                    VehicleTelemetry.device_id > previous
                )
            )
            if device_id is None:
                return False
            previous = device_id
            if device_id in on_file:
                continue
            found = await self.db.scalar(
                select(VehicleTelemetry.id)
                .where(
                    VehicleTelemetry.device_id == device_id,
                    VehicleTelemetry.param_key == param_key,
                )
                .limit(1)
            )
            if found is not None:
                return True

    async def _odometer_record_max(self, vin: str) -> float:
        """The vehicle's highest odometer record in km, or 0 with none."""
        found = await self.db.execute(
            select(func.max(OdometerRecord.odometer_km)).where(OdometerRecord.vin == vin)
        )
        return float(found.scalar() or 0)

    async def _sanitize_odometer_value(
        self, vin: str, value: float, *, record_max: float | None = None
    ) -> float | None:
        """Sanitize an odometer value (km), returning None if invalid.

        Applies the same sanity checks as _sync_odometer_from_telemetry:
        - Absolute cap at ~1.6 million km (1M mi equivalent)
        - Reject unreasonable jumps (>16,000 km from existing max)
        - Reject negative/zero values

        ``record_max`` is the vehicle's highest record when the caller already
        has it (an SD pull checks thousands of rows against one).

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

        # Max existing odometer_km, to check for unreasonable jumps
        max_odometer_km = (
            record_max if record_max is not None else await self._odometer_record_max(vin)
        )

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
        for param_key in normalised & autopid_data.keys():
            await self._label_odometer_km(parameters.get(param_key))

        # Validate telemetry values before storage
        validator = TelemetryValidator(self.db)
        valid_data, _rejected = await validator.validate_batch(
            vin, autopid_data, parameters, device_id=device_id, sample_at=timestamp
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
            # keys (B6-11). A dropped one is skipped whole, as live drops it.
            if self._is_odometer_param(r.param_key):
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
        """
        from app.services.session_service import SessionService  # local import avoids cycle

        sessions = await self._closed_sessions_in_span(vin, device_id, start, end)
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
                replace(r, value=float(converted[r.param_key]))
                if r.param_key in normalised and converted.get(r.param_key) is not None
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

        `odometer_normalised`: storage normalised this batch's odometer
        (`normalises_odometer`), so an odometer key, by the same match
        normalisation used (`declared_odometer_key` is the device's
        `odometer_param_key`), holds km. So does `ODOMETER_MI`, on every path.
        The alert then reads in the owner's distance unit whatever the
        parameter row's unit says. An odometer-named key that wasn't
        normalised prints raw unless its row says km.
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

        # Odometer-named counts too: on a device that declares another key it
        # wasn't normalised, and a unitless row isn't proof of km (carry 15).
        # Normalised is the declared match, or ODOMETER_MI, which every path
        # converts (R1-M1).
        odometer_key = self._is_odometer_param(
            param_key, declared_odometer_key
        ) or self._is_odometer_param(param_key)
        normalised = (
            odometer_normalised and self._is_odometer_param(param_key, declared_odometer_key)
        ) or is_miles_odometer_key(param_key)
        quantity = alert_quantity(
            param.param_class,
            param.unit,
            odometer_key=odometer_key,
            odometer_normalised=normalised,
        )

        # Held from here, as a send nothing took would be: the frames that land
        # while this one is out wait like the rest. A delivered send clears it
        # and stamps the cooldown instead (`deliver_threshold_alert`).
        cooldown_minutes = await livelink.get_alert_cooldown_minutes()
        param.alert_retry_at = now + timedelta(minutes=cooldown_minutes)
        await self._send_alert(
            ThresholdAlert(
                param_id=param.id,
                param_key=param_key,
                band=band,
                once=once,
                at=now,
                vehicle_name=vehicle_name,
                parameter_name=param.display_name or param_key,
                value=value,
                threshold_value=band_line(band, param),
                unit=param.unit,
                ctx=await render_context_for_vehicle(self.db, vin),
                quantity=quantity,
            )
        )

    async def _send_alert(self, alert: ThresholdAlert) -> None:
        """Send it once the caller's transaction commits, in the background.

        Not inline (B6-1): a slow notification service held up the MQTT frame,
        and every frame queued behind it, once per cooldown. A rollback drops
        it, so a frame that failed to store alerts nobody.
        """
        after_commit(
            self.db,
            partial(deliver_threshold_alert, alert=alert),
            label=f"threshold alert for {alert.param_key}",
        )

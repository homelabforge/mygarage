"""Session service for drive session detection and management."""

import logging
from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.livelink_device import LiveLinkDevice
from app.models.vehicle_telemetry import VehicleTelemetry
from app.services.session_boundaries import (
    BOUNDARY_ALGORITHM_MOVEMENT,
    PENDING_SOURCE_RPM,
    MovementSignals,
    extract_signals,
)
from app.utils.datetime_utils import utc_now
from app.utils.movement_keys import rpm_param_key_candidates, speed_param_key_candidates
from app.utils.odometer_units import is_odometer_param_key

logger = logging.getLogger(__name__)

# Every spelling of speed and RPM, for the aggregate reader's SQL `IN` lists.
# Derived from `app.utils.movement_keys` rather than written here, so the keys
# that can OPEN a session and the keys the aggregates can READ are one set. They
# were two: `SPEED_PARAM_KEYS` was a hand-written module constant and the RPM
# list was inline in `_calculate_session_aggregates` twelve lines below it,
# neither aware of the other.
SPEED_PARAM_KEYS = speed_param_key_candidates()
RPM_PARAM_KEYS = rpm_param_key_candidates()

#: Below this speed the vehicle is not moving, in km/h. Hoisted out of
#: `_calculate_driving_insights`, where it was a local, so the movement
#: predicate can share it: "moving" must mean one thing in this subsystem, and
#: a session that opened at 1 km/h while idle accounting called the same sample
#: stationary is a contradiction the code cannot resolve.
IDLE_THRESHOLD_KMH = 5.0

#: Keys a PARKED vehicle publishes on its own. A batch containing nothing else
#: is a heartbeat, not a vehicle whose movement went unread, so it must not
#: trigger the no-movement diagnostic below -- otherwise the warning fires for
#: every device on every instance and means nothing.
PARKED_HEARTBEAT_KEYS = frozenset({"BATTERY_VOLTAGE"})

#: Every column `refresh_aggregates` derives from a session's window. Listed so
#: `clear_first` can null them all; a column added to the recompute steps but
#: not here would survive a rebound as a stale figure from the wider window.
_DERIVED_SESSION_COLUMNS = (
    "start_odometer",
    "end_odometer",
    "distance_km",
    "avg_speed",
    "max_speed",
    "avg_rpm",
    "max_rpm",
    "avg_coolant_temp",
    "max_coolant_temp",
    "avg_throttle",
    "max_throttle",
    "avg_fuel_level",
    "idle_seconds",
    "harsh_accel_count",
    "harsh_brake_count",
)

#: Devices already named by `_warn_if_no_movement_signal_ever`, this process.
#: See that method for why this is process-local rather than a column.
_NO_MOVEMENT_WARNED: set[str] = set()


class SessionService:
    """Service for drive session detection and aggregation."""

    def __init__(self, db: AsyncSession):
        """Initialize with database session."""
        self.db = db

    # =========================================================================
    # Session Detection
    # =========================================================================

    async def handle_ecu_status_change(
        self,
        device: LiveLinkDevice,
        new_ecu_status: str,
        timestamp: datetime,
    ) -> DriveSession | None:
        """Handle ECU status transition for session detection.

        Args:
            device: The device reporting the status
            new_ecu_status: New ECU status (online/offline)
            timestamp: When the status changed

        Returns:
            DriveSession if session started/ended, None otherwise
        """
        if not device.vin:
            return None  # Device not linked to vehicle

        old_status = device.ecu_status or "unknown"

        # ECU online marks the device online and NOTHING MORE.
        #
        # This is the single change that covers all three live ingest sites --
        # MQTT `can/rx`, MQTT `can/status`, and the HTTPS status block -- which
        # is why it belongs here rather than at any one caller. An earlier
        # revision of the design fixed only `mqtt_subscriber`'s telemetry-
        # inferred path, and the comment above that path says it "handles WiCAN
        # devices that don't send explicit can/status messages": by the code's
        # own account the FALLBACK. An instance whose dongle sends status
        # messages, or any instance on HTTPS ingest, would have kept 100% of its
        # phantom sessions while the changelog claimed they were fixed.
        #
        # `contact` mode restores the old behaviour verbatim, for a device whose
        # movement signals nothing recognises.
        if old_status != "online" and new_ecu_status == "online":
            if await self._boundary_mode() == "contact":
                return await self.start_session(device, timestamp)
            return None

        # ECU went offline -> end current session
        if old_status == "online" and new_ecu_status == "offline":
            if device.current_session_id:
                return await self.end_session(device, timestamp)

        return None

    async def handle_ecu_online(self, vin: str, device_id: str) -> DriveSession | None:
        """Handle ECU coming online - convenience method for route.

        Args:
            vin: Vehicle VIN
            device_id: Device ID

        Returns:
            DriveSession if a new session was started
        """
        device = await self._get_device(device_id)
        if not device or device.vin != vin:
            return None

        return await self.handle_ecu_status_change(
            device=device,
            new_ecu_status="online",
            timestamp=utc_now(),
        )

    async def handle_ecu_offline(self, vin: str, device_id: str) -> DriveSession | None:
        """Handle ECU going offline - convenience method for route.

        Args:
            vin: Vehicle VIN
            device_id: Device ID

        Returns:
            DriveSession if a session was ended
        """
        device = await self._get_device(device_id)
        if not device or device.vin != vin:
            return None

        return await self.handle_ecu_status_change(
            device=device,
            new_ecu_status="offline",
            timestamp=utc_now(),
        )

    async def _get_device(self, device_id: str) -> LiveLinkDevice | None:
        """Get a device by ID."""
        result = await self.db.execute(
            select(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id)
        )
        return result.scalar_one_or_none()

    async def start_session(
        self,
        device: LiveLinkDevice,
        timestamp: datetime,
    ) -> DriveSession:
        """Start a new drive session.

        Args:
            device: The device starting the session
            timestamp: Session start time

        Returns:
            The new DriveSession
        """
        if not device.vin:
            raise ValueError("Device must be linked to start a session")

        # End any existing session first
        if device.current_session_id:
            await self.end_session(device, timestamp)

        # Get start odometer if available
        start_odometer = await self._get_current_odometer(device.vin)

        # Create new session
        session = DriveSession(
            vin=device.vin,
            device_id=device.device_id,
            started_at=timestamp,
            start_odometer=start_odometer,
        )
        self.db.add(session)
        await self.db.flush()

        # Update device with current session.
        #
        # `ecu_status` is deliberately NOT written here. Once a session is no
        # longer a proxy for ECU state, a movement timeout would mark a device
        # whose ECU is awake as offline -- and that is not cosmetic:
        # `device_command_service.py` refuses any `requires_ecu` command when
        # `ecu_status != "online"`, so the whole remote-command surface would go
        # dead after every drive. `routes/torque.py` already carries a
        # workaround comment for exactly this coupling.
        device.current_session_id = session.id

        logger.info(
            "Started drive session %d for vehicle %s (device %s)",
            session.id,
            device.vin,
            device.device_id,
        )
        return session

    async def end_session(
        self,
        device: LiveLinkDevice,
        timestamp: datetime,
        *,
        retain_pointer: bool = False,
    ) -> DriveSession | None:
        """End the current drive session and calculate aggregates.

        Args:
            device: The device ending the session
            timestamp: Session end time
            retain_pointer: Keep ``current_session_id`` pointing at the closed
                session, putting the device in the ``awaiting`` state so
                movement returning inside the drive gap REOPENS this session
                instead of creating a second one. Set only by the contact-loss
                clock. Without it, movement then six minutes of silence then
                movement produces two live sessions and one replayed session,
                and the claim that a drive is cut the same way whichever path it
                arrived by is aspirational.

        Returns:
            The ended DriveSession, or None if no active session
        """
        if not device.current_session_id:
            return None

        # Get the current session
        result = await self.db.execute(
            select(DriveSession).where(DriveSession.id == device.current_session_id)
        )
        session = result.scalar_one_or_none()

        if not session:
            device.current_session_id = None
            return None

        # Calculate session duration
        session.ended_at = timestamp
        if session.started_at:
            # Ensure both datetimes are naive UTC for subtraction
            started = session.started_at
            if started.tzinfo is not None:
                started = started.replace(tzinfo=None)
            ended = timestamp
            if ended.tzinfo is not None:
                ended = ended.replace(tzinfo=None)
            duration = (ended - started).total_seconds()
            session.duration_seconds = int(duration)

        # Same derivation the repair paths use, so a session summarised on close
        # and one recomputed months later cannot disagree about how it was made.
        await self.refresh_aggregates(session)

        # Clear device's current session unless it is being retained for the
        # reopen window. `ecu_status` is deliberately not written -- see
        # `start_session`.
        if not retain_pointer:
            device.current_session_id = None

        logger.info(
            "Ended drive session %d for vehicle %s (duration: %d seconds)",
            session.id,
            device.vin,
            session.duration_seconds or 0,
        )
        return session

    # =========================================================================
    # Movement-based session boundaries
    # =========================================================================

    async def _gap_minutes(self) -> int:
        from app.services.livelink_service import LiveLinkService  # local: avoids a cycle

        return await LiveLinkService(self.db).get_session_gap_minutes()

    async def _boundary_mode(self) -> str:
        from app.services.livelink_service import LiveLinkService  # local: avoids a cycle

        return await LiveLinkService(self.db).get_session_boundary_mode()

    @staticmethod
    def _naive(value: datetime) -> datetime:
        """Naive UTC, matching every stored timestamp in this subsystem."""
        return value.replace(tzinfo=None) if value.tzinfo is not None else value

    @staticmethod
    def _clear_movement_state(device: LiveLinkDevice) -> None:
        """Reset all four pending fields together.

        They are one envelope, not four independent flags: `pending_since` says
        a warm-up is under way, `pending_source` says which signal opened it,
        and the candidate/baseline pair is the evidence window. Clearing a
        subset leaves a half-state no transition in the machine describes.
        """
        device.pending_since = None
        device.pending_source = None
        device.movement_candidate_at = None
        device.movement_baseline_km = None

    async def observe_telemetry(
        self,
        device: LiveLinkDevice,
        samples: Mapping[str, object],
        sample_at: datetime,
        *,
        live: bool = True,
    ) -> DriveSession | None:
        """Decide what one telemetry batch means for this device's session.

        The input edge of the state machine. Called once per ingested payload
        from the live paths (MQTT and HTTPS, via `TelemetryService`), and never
        from the Torque path -- Torque supplies an authoritative session id from
        the phone, so a movement predicate has nothing to add there and would
        only overrule a better source.

        ``sample_at`` is the SAMPLE time, not the receipt time. ``live=False``
        marks a replay: it may open and extend sessions, but must not write
        ``last_movement_at``, because that field anchors every live timeout and
        an HTTPS payload carrying an old or future timestamp would drag a live
        session hours away from where it belongs.

        Returns the open session, if there now is one.
        """
        if not device.vin or not device.enabled:
            return None
        if await self._boundary_mode() == "contact":
            return None

        sample_at = self._naive(sample_at)
        gap = await self._gap_minutes()
        window = timedelta(minutes=gap)
        signals = extract_signals(samples)

        session = await self._live_session(device)

        # Expire a stale evidence window BEFORE evaluating this batch. Without a
        # bound, an engine-on at 08:00 and a movement sample at 17:00 are still
        # "consecutive", and the session backdates nine hours of parked
        # telemetry into a drive. Two samples separated by a disconnect are not
        # consecutive in any sense that matters.
        if session is None:
            if device.pending_since is not None and (
                sample_at - self._naive(device.pending_since) > window
            ):
                self._clear_movement_state(device)
            elif device.movement_candidate_at is not None and (
                sample_at - self._naive(device.movement_candidate_at) > window
            ):
                device.movement_candidate_at = None
                device.movement_baseline_km = None

        confirmed = self._confirm_movement(device, signals, sample_at, session is not None)

        if confirmed:
            return await self._promote_to_driving(device, signals, sample_at, gap, live=live)

        if session is not None:
            # `driving` -> `stopped`: connected, moved before, not moving now.
            # Nothing to do; the session stays open and the drive-gap clock in
            # `check_session_timeouts` decides when the stop becomes two trips.
            return session

        if not signals.has_any_signal:
            self._warn_if_no_movement_signal_ever(device, samples)

        if signals.is_engine_on and device.pending_since is None:
            # `idle` -> `pending`. Engine turning with the vehicle stationary is
            # a remote start, a diagnostic session, a winter warm-up, or the
            # eleven-minute driveway idle that was credited with 14 km. It
            # buffers the burst so a drive that follows keeps its warm-up
            # samples, and is discarded outright if no movement follows.
            device.pending_since = sample_at
            device.pending_source = PENDING_SOURCE_RPM
            if signals.odometer_km is not None and device.movement_baseline_km is None:
                device.movement_baseline_km = Decimal(str(signals.odometer_km))
                device.movement_candidate_at = sample_at

        return None

    def _warn_if_no_movement_signal_ever(
        self, device: LiveLinkDevice, samples: Mapping[str, object]
    ) -> None:
        """Name a device whose movement this code cannot see.

        A silent zero is the failure mode this entire change exists to
        eliminate, so reintroducing one for the cohort the movement predicate
        cannot read would be absurd. "No sessions, cause unknown" is not
        something an operator can act on; "this device publishes
        CUSTOM_ROAD_SPEED and nothing recognises it" is -- either a param alias
        is missing, or the instance wants `livelink_session_boundary_mode =
        contact`.

        Fires only for a device that is plainly OPERATING -- publishing engine
        telemetry -- while reporting nothing recognisable as speed, RPM or an
        odometer. A parked vehicle publishing only its battery heartbeat should
        produce no sessions, and flagging that would make the warning
        meaningless on every instance.

        Logged once per device per process, via a module-level set. Deliberately
        not a column: a device sends a payload every few seconds, so logging per
        payload would bury the diagnostic it exists to surface, while persisting
        the fact would need a migration to say something the log says well
        enough. Resetting on restart is a feature -- it re-reports a problem
        that is still present.
        """
        if device.last_movement_at is not None:
            return
        if device.device_id in _NO_MOVEMENT_WARNED:
            return
        operating_keys = sorted(key for key in samples if key.upper() not in PARKED_HEARTBEAT_KEYS)
        if not operating_keys:
            return
        _NO_MOVEMENT_WARNED.add(device.device_id)
        logger.warning(
            "Device %s reports engine telemetry but no recognised movement signal; "
            "it will record no drive sessions. Keys seen: %s. Either a parameter "
            "alias is missing from app/utils/movement_keys.py, or set "
            "livelink_session_boundary_mode=contact for this instance.",
            device.device_id,
            ", ".join(operating_keys),
        )

    def _confirm_movement(
        self,
        device: LiveLinkDevice,
        signals: MovementSignals,
        sample_at: datetime,
        session_is_open: bool,
    ) -> bool:
        """Does this batch prove the vehicle moved? Records evidence if not yet.

        Three signals, per C2. Speed needs TWO consecutive above-floor samples,
        because a single one is effectively unvalidatable:
        `validate_rate_of_change` skips entirely when the previous reading is
        older than `RATE_CHECK_MAX_AGE_SECONDS = 120`, which is exactly the
        parked-heartbeat case. An odometer increase across the same window is
        the signal that covers a device whose speed arrives under a name nothing
        recognises. RPM proves only that the engine is turning.

        Once a session is open the debounce is spent: the vehicle has already
        been proven to move, so one above-floor sample extends the drive.

        ``movement_candidate_at`` anchors the evidence window for BOTH signals.
        One consequence is worth stating rather than discovering: an above-floor
        sample, a below-floor sample, and another above-floor sample inside one
        gap window will confirm, even though they are not literally consecutive.
        That is accepted -- the debounce exists to suppress a SINGLE spike, and
        the parked heartbeat this whole change is about carries no speed key at
        all, so it never sets a candidate in the first place.
        """
        if session_is_open:
            if signals.is_above_floor:
                return True
            if signals.odometer_km is not None and device.movement_baseline_km is not None:
                return signals.odometer_km > float(device.movement_baseline_km)
            return False

        if signals.is_above_floor:
            if device.movement_candidate_at is not None:
                return True
            device.movement_candidate_at = sample_at
            if signals.odometer_km is not None:
                device.movement_baseline_km = Decimal(str(signals.odometer_km))
            return False

        if signals.odometer_km is not None:
            if device.movement_baseline_km is not None:
                if signals.odometer_km > float(device.movement_baseline_km):
                    return True
                # A parked vehicle republishes the same odometer on every
                # heartbeat, and a REPLAY can report a lower one. Neither is
                # movement, and neither should advance the baseline past what
                # has actually been observed.
                return False
            device.movement_baseline_km = Decimal(str(signals.odometer_km))
            if device.movement_candidate_at is None:
                device.movement_candidate_at = sample_at

        return False

    async def _live_session(self, device: LiveLinkDevice) -> DriveSession | None:
        """The device's OPEN session, or None.

        Distinct from `get_current_session`, which returns whatever the pointer
        names -- and in the `awaiting` state the pointer deliberately names a
        CLOSED session.
        """
        if not device.current_session_id:
            return None
        session = (
            await self.db.execute(
                select(DriveSession).where(DriveSession.id == device.current_session_id)
            )
        ).scalar_one_or_none()
        if session is None or session.ended_at is not None:
            return None
        return session

    async def _promote_to_driving(
        self,
        device: LiveLinkDevice,
        signals: MovementSignals,
        sample_at: datetime,
        gap: int,
        *,
        live: bool,
    ) -> DriveSession:
        """Movement is confirmed: open, reopen or extend a session."""
        session = await self._live_session(device)

        if session is None:
            session = await self._reopen_awaiting(device, sample_at, gap)
        if session is None:
            session = await self._open_session_for_movement(device, sample_at, gap)

        if session.movement_started_at is None:
            session.movement_started_at = sample_at
        session.movement_ended_at = sample_at
        if signals.odometer_km is not None:
            device.movement_baseline_km = Decimal(str(signals.odometer_km))
        if live:
            device.last_movement_at = sample_at

        device.pending_since = None
        device.pending_source = None
        device.movement_candidate_at = None
        return session

    async def _reopen_awaiting(
        self, device: LiveLinkDevice, sample_at: datetime, gap: int
    ) -> DriveSession | None:
        """Reopen the session the contact-loss clock closed, if still in reach.

        The `awaiting` state exists so live and replay agree. The contact
        timeout still CLOSES promptly -- a device that never returns must not be
        left open -- but the session stays reopenable until the drive gap
        expires, so a six-minute silence in the middle of one drive does not
        become two.
        """
        if not device.current_session_id:
            return None
        retained = (
            await self.db.execute(
                select(DriveSession).where(DriveSession.id == device.current_session_id)
            )
        ).scalar_one_or_none()
        if retained is None or retained.ended_at is None:
            device.current_session_id = None if retained is None else device.current_session_id
            return None

        anchor = self._naive(retained.movement_ended_at or retained.ended_at)
        if sample_at - anchor > timedelta(minutes=gap):
            device.current_session_id = None
            return None

        retained.ended_at = None
        retained.duration_seconds = None
        logger.info(
            "Reopened drive session %d for device %s (movement returned within the %d-minute gap)",
            retained.id,
            device.device_id,
            gap,
        )
        return retained

    async def _open_session_for_movement(
        self, device: LiveLinkDevice, sample_at: datetime, gap: int
    ) -> DriveSession:
        """Open a session whose window keeps the whole opening burst.

        ``started_at`` backdates to the earliest evidence of this drive -- the
        engine-on that opened the pending state, or the first above-floor sample
        -- NOT to the sample that confirmed movement. Aggregates are strictly
        window-bounded, so setting it to the confirming sample silently discards
        warm-up coolant, initial fuel level and, critically, the OPENING
        ODOMETER READING. `_calculate_session_distance` then finds exactly one
        odometer sample in the window and assigns unconditionally, writing
        ``start_odometer == end_odometer`` and ``distance_km = 0.0``: a
        confident zero, not a blank.

        The tail is trimmed rather than kept, which reads as inconsistent and is
        deliberate. The opening burst carries real readings; the closing tail
        carries only parked heartbeats, and stamping ``ended_at`` at the last
        contact pads every drive by up to one heartbeat interval (95 minutes,
        measured) and drags ``avg_speed`` toward zero. See
        `check_session_timeouts`.

        ``started_at`` is also clamped past the previous session's close. C5's
        whole-burst rule applies to the OPENING burst of a drive; it cannot
        apply to a burst already consumed by a previous session, because every
        aggregate is a window scan and two overlapping sessions both claim the
        same samples and both report the same distance.
        """
        candidates = [
            self._naive(value)
            for value in (device.pending_since, device.movement_candidate_at)
            if value is not None
        ]
        started_at = min([*candidates, sample_at])
        movement_started_at = (
            self._naive(device.movement_candidate_at)
            if device.movement_candidate_at is not None
            else sample_at
        )

        previous_end = (
            await self.db.execute(
                select(func.max(DriveSession.ended_at))
                .where(DriveSession.device_id == device.device_id)
                .where(DriveSession.ended_at.is_not(None))
            )
        ).scalar()
        if previous_end is not None:
            previous_end = self._naive(previous_end)
            if started_at < previous_end:
                started_at = previous_end
            if movement_started_at < started_at:
                movement_started_at = started_at

        # A row lock through creation, so two concurrent first-movement payloads
        # cannot both read a NULL pointer and both create. The partial unique
        # index `uq_drive_sessions_open_per_device` is the real backstop; this
        # keeps the common case from ever reaching it. No-op on SQLite, whose
        # single writer serialises anyway.
        if self.db.bind is not None and self.db.bind.dialect.name == "postgresql":
            await self.db.execute(
                select(LiveLinkDevice.id).where(LiveLinkDevice.id == device.id).with_for_update()
            )

        session = DriveSession(
            vin=device.vin,
            device_id=device.device_id,
            started_at=started_at,
            movement_started_at=movement_started_at,
            movement_ended_at=sample_at,
            start_odometer=await self._get_current_odometer(device.vin),
            boundary_algorithm_version=BOUNDARY_ALGORITHM_MOVEMENT,
            effective_gap_minutes=gap,
        )
        self.db.add(session)
        await self.db.flush()
        device.current_session_id = session.id

        logger.info(
            "Opened drive session %d for %s (device %s) on confirmed movement at %s",
            session.id,
            device.vin,
            device.device_id,
            sample_at,
        )
        return session

    async def begin_provisional_offline(
        self, device: LiveLinkDevice, now: datetime | None = None
    ) -> None:
        """Record an explicit ECU-offline as PROVISIONAL, changing nothing else.

        Pending state is deliberately NOT cleared here. Taken separately,
        "clear pending on explicit offline" and "treat offline as provisional
        for 60 seconds" mean a brief WiFi drop discards the warm-up and
        opening-odometer samples the pending state exists to preserve. It clears
        when the offline FINALIZES.
        """
        device.pending_offline_at = self._naive(now or utc_now())

    async def finalize_offline(
        self, device: LiveLinkDevice, now: datetime | None = None
    ) -> DriveSession | None:
        """Close the session on a finalized ECU-offline, directly.

        Not by looking for an online-to-offline transition. The ingest routes
        persist ``ecu_status='offline'`` the moment it arrives, so by the time
        the grace period expires `handle_ecu_status_change` sees offline ->
        offline, no-ops, and leaves the session to a contact timeout anchored on
        a ``last_seen`` that the finalizer itself had advanced. The pre-existing
        tests mock `handle_ecu_offline` and assert only that it was called, so
        they pass with this broken.

        This never touches ``last_seen``: there was no contact, and fabricating
        one corrupts every timeout that reads it.
        """
        now = self._naive(now or utc_now())
        session = await self._live_session(device)
        closed = None
        if session is not None:
            end_at = self._naive(
                session.movement_ended_at or session.movement_started_at or session.started_at
            )
            closed = await self.end_session(device, min(end_at, now))
        device.pending_offline_at = None
        self._clear_movement_state(device)
        return closed

    async def expire_stale_movement_state(
        self, gap_minutes: int | None = None, now: datetime | None = None
    ) -> int:
        """Discard pending drives and finalize `awaiting` closures past the gap.

        Two housekeeping jobs the live path cannot do, because both are defined
        by the ABSENCE of a payload:

        - a pending drive older than the gap is discarded, and no session was
          ever created for it. A warm-up that went nowhere leaves no trace.
        - an `awaiting` session past the gap can no longer be reopened, so the
          pointer is cleared and the closure becomes final.

        Returns the number of device rows changed.
        """
        now = self._naive(now or utc_now())
        if gap_minutes is None:
            gap_minutes = await self._gap_minutes()
        window = timedelta(minutes=gap_minutes)
        changed = 0

        stale_pending = (
            (
                await self.db.execute(
                    select(LiveLinkDevice)
                    .where(LiveLinkDevice.pending_since.is_not(None))
                    .where(LiveLinkDevice.pending_since < now - window)
                )
            )
            .scalars()
            .all()
        )
        for device in stale_pending:
            self._clear_movement_state(device)
            changed += 1

        awaiting = (
            await self.db.execute(
                select(LiveLinkDevice, DriveSession)
                .join(DriveSession, DriveSession.id == LiveLinkDevice.current_session_id)
                .where(DriveSession.ended_at.is_not(None))
            )
        ).all()
        for device, session in awaiting:
            anchor = self._naive(session.movement_ended_at or session.ended_at)
            if now - anchor > window:
                device.current_session_id = None
                changed += 1

        return changed

    async def resolve_torque_session(
        self,
        device: LiveLinkDevice,
        torque_session_id: str | None,
        timestamp: datetime,
    ) -> DriveSession | None:
        """Find-or-create a DriveSession for a Torque `session` id. Replay/out-of-order safe."""
        device.last_seen = utc_now().replace(
            tzinfo=None
        )  # server clock drives inactivity finalize (R1-H7)
        started = timestamp.replace(tzinfo=None) if timestamp.tzinfo is not None else timestamp

        if torque_session_id is None:
            if not device.current_session_id:
                return None
            return (
                await self.db.execute(
                    select(DriveSession).where(DriveSession.id == device.current_session_id)
                )
            ).scalar_one_or_none()

        existing = (
            await self.db.execute(
                select(DriveSession).where(
                    DriveSession.device_id == device.device_id,
                    DriveSession.external_session_id == torque_session_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            # Replay/continuation of a KNOWN session id: append data only. Never move the
            # current-session pointer (a late older-session packet must not drag it backward)
            # and never finalize anything (a late packet must not end the active trip). (R1-H2, R2-H1)
            return existing

        # NEW (first-seen) session id. Decide whether it is the newest drive or a late straggler
        # from an OLDER drive whose first packet arrived after a newer trip went active (R3-H1).
        current = None
        if device.current_session_id:
            current = (
                await self.db.execute(
                    select(DriveSession).where(DriveSession.id == device.current_session_id)
                )
            ).scalar_one_or_none()
        is_newer = current is None or current.started_at is None or started >= current.started_at

        if not is_newer:
            # Chronologically-older first-seen session: record it as an already-closed trip so it
            # never leaks open, and do NOT finalize or unseat the active newer trip. (R3-H1)
            session = DriveSession(
                vin=device.vin,
                device_id=device.device_id,
                started_at=started,
                ended_at=started,
                duration_seconds=0,
                external_session_id=torque_session_id,
            )
            self.db.add(session)
            await self.db.flush()
            return session

        # Newest drive: finalize the prior (older) open session so it does not leak open, THEN
        # open the new one and advance the pointer.
        if device.current_session_id:
            await self.end_session(
                device, utc_now().replace(tzinfo=None)
            )  # server-now end >= prior start (R2-H1, R2-H2)
        # Deliberately do NOT set start_odometer here. _get_current_odometer() is VIN-scoped,
        # not device-scoped, so on a vehicle with BOTH a WiCAN dongle and a Torque source it
        # would attribute the co-located WiCAN device's odometer to this Torque trip. Torque
        # has no odometer PID at all -> leave start_odometer None so end_session's odometer-
        # delta gate never fires, forcing distance to come from the GPS breadcrumb fallback.
        session = DriveSession(
            vin=device.vin,
            device_id=device.device_id,
            started_at=started,
            external_session_id=torque_session_id,
        )
        self.db.add(session)
        await self.db.flush()
        device.current_session_id = session.id
        return session

    async def _get_current_odometer(self, vin: str) -> float | None:
        """Get the current odometer reading from latest telemetry, in kilometres.

        Matching is by key *shape*, not an exact name list: the standard SAE
        J1979 key is `A6-ODOMETER`, and an exact-match list that omitted it left
        every session on a standard-PID device with no odometer and no distance.

        No conversion happens here. `TelemetryService.store_telemetry`
        normalises the odometer to canonical km on the way in, so the stored
        latest value is already metric and converting again would square the
        factor. Test `test_ingest_then_session_converts_exactly_once` drives
        ingest and session together and fails if this starts converting.
        """
        from app.models.vehicle_telemetry import VehicleTelemetryLatest

        result = await self.db.execute(
            select(VehicleTelemetryLatest.param_key, VehicleTelemetryLatest.value).where(
                VehicleTelemetryLatest.vin == vin
            )
        )
        for param_key, value in result.all():
            if value is not None and is_odometer_param_key(param_key):
                return float(value)
        return None

    async def refresh_aggregates(self, session: DriveSession, *, clear_first: bool = False) -> None:
        """Recompute a closed session's aggregates from the telemetry now on record.

        A WiCAN buffers readings while off home WiFi and replays them with their
        original timestamps, so a session's telemetry can keep arriving long
        after `end_session` computed its aggregates from the handful of samples
        that made it in live.

        The single derivation of a session's numbers: `end_session` calls it on
        close, `TelemetryService` calls it when a reading or an SD-card pull
        lands inside a closed session's window, and `tools/
        recompute_session_aggregates.py` calls it to repair history.

        ``clear_first`` nulls every derived column before recomputing, and is
        for callers that have NARROWED the window. The recompute steps assign
        only when they find samples and never clear, which is right for the
        scheduled refresh -- telemetry is pruned on a retention schedule while
        sessions are kept forever, so an old session's window is legitimately
        empty and blanking it would erase the only record of that drive. It is
        exactly wrong after a rebound: a session cut down from 95 minutes of
        parked heartbeats to the four the vehicle moved would keep the
        ``avg_speed`` the wide window produced.

        Two callers wanting opposite things is why this is a parameter. It
        defaults to False because a default of True would blank every pruned
        session on the next scheduler tick -- destroying data rather than
        misreporting it.
        """
        if clear_first:
            for column in _DERIVED_SESSION_COLUMNS:
                setattr(session, column, None)
        await self._calculate_session_distance(session)
        await self._calculate_session_aggregates(session)
        await self._calculate_driving_insights(session)

    async def _calculate_session_distance(self, session: DriveSession) -> None:
        """Set the odometer span and distance from samples inside the window.

        Sessions open and close on device connectivity, not on the engine, so a
        vehicle regularly drives while no session is open. Taking the odometer
        from `vehicle_telemetry_latest` at each end -- the newest value on
        record, whatever its age -- charged all of that driving to whichever
        session happened to open next: a Ram idling in the driveway for eleven
        minutes at a top speed of 2 km/h was credited with 14 km, and an earlier
        one with 129 km.

        Only movement observed between `started_at` and `ended_at` belongs to
        this session. Driving that happened in the gaps belongs to no session,
        and recovering it needs correct session boundaries rather than a wider
        odometer lookup.

        Nothing is assigned when the window yields no distance either way,
        matching `_calculate_session_aggregates`: telemetry is pruned on a
        retention schedule while sessions are kept forever, so an old session's
        window is legitimately empty and must not be blanked.
        """
        if not session.started_at or not session.ended_at:
            return

        # One grouped pass over the window. Odometer keys cannot be an `IN`
        # list -- the standard SAE J1979 key carries an arbitrary two-hex-digit
        # PID prefix (`A6-ODOMETER`) and a WiCAN autopid has none at all -- and
        # a substring match would swallow trip counters like `21-DISTANCEMILON`
        # (see app/utils/odometer_units.py). Grouping by key lets
        # `is_odometer_param_key` decide in Python without a second scan, and
        # keeps any function off the indexed `param_key` column.
        result = await self.db.execute(
            select(
                VehicleTelemetry.param_key,
                func.min(VehicleTelemetry.value),
                func.max(VehicleTelemetry.value),
            )
            .where(VehicleTelemetry.vin == session.vin)
            # Scoped to the session's own device, not just its VIN. One vehicle
            # can carry both a WiCAN dongle and a Torque source, and
            # `resolve_torque_session` deliberately leaves `start_odometer`
            # unset so a Torque trip cannot be stamped from the co-located
            # WiCAN's odometer. Matching on VIN alone walks back through that.
            .where(VehicleTelemetry.device_id == session.device_id)
            .where(VehicleTelemetry.timestamp >= session.started_at)
            .where(VehicleTelemetry.timestamp <= session.ended_at)
            .group_by(VehicleTelemetry.param_key)
        )
        spans = [
            (low, high)
            for key, low, high in result.all()
            if low is not None and high is not None and is_odometer_param_key(key)
        ]

        if spans:
            low = min(pair[0] for pair in spans)
            high = max(pair[1] for pair in spans)
            session.start_odometer = float(low)
            session.end_odometer = float(high)
            session.distance_km = float(high) - float(low)
            return

        # No odometer in the window. A Torque trip never has one -- the app
        # reports no odometer PID -- so its distance comes from the GPS
        # breadcrumb. This lives here rather than in `end_session` so every
        # caller gets the same policy: computed only in `end_session`, a
        # Torque session's distance stayed frozen at whatever the breadcrumb
        # held on close while its speed and RPM were repaired around it.
        from app.services.location_service import LocationService  # local import avoids cycle

        points = await LocationService(self.db).get_trip_points(session.vin, session.id)
        if len(points) >= 2:
            coords = [(float(p.latitude), float(p.longitude)) for p in points]
            session.distance_km = float(LocationService.haversine_km(coords))

    async def _calculate_session_aggregates(self, session: DriveSession) -> None:
        """Calculate aggregate statistics for a session from telemetry data."""
        if not session.started_at or not session.ended_at:
            return

        # Define which parameters to aggregate.
        # Each entry maps to a list of possible param_key names to check,
        # since different WiCAN firmware/configs use different naming conventions
        # (e.g. OBD2 PID-prefixed "0D-VehicleSpeed" vs generic "SPEED").
        aggregate_mappings = {
            "speed": (SPEED_PARAM_KEYS, "avg_speed", "max_speed"),
            "rpm": (RPM_PARAM_KEYS, "avg_rpm", "max_rpm"),
            "coolant": (
                ["COOLANT_TMP", "05-EngineCoolantTemp", "05-ENGINECOOLANTTEMP"],
                "avg_coolant_temp",
                "max_coolant_temp",
            ),
            "throttle": (
                ["THROTTLE", "11-ThrottlePosition", "11-THROTTLEPOSITION"],
                "avg_throttle",
                "max_throttle",
            ),
            "fuel": (["FUEL", "2F-FuelTankLevel", "2F-FUELTANKLEVEL"], "avg_fuel_level", None),
        }

        for _, (param_keys, avg_attr, max_attr) in aggregate_mappings.items():
            stats = await self._get_param_stats_multi(
                session.vin,
                session.device_id,
                param_keys,
                session.started_at,
                session.ended_at,
            )
            count = stats.get("count")
            if count and count > 0:
                if avg_attr:
                    setattr(session, avg_attr, stats["avg"])
                if max_attr:
                    setattr(session, max_attr, stats["max"])

    async def _calculate_driving_insights(self, session: DriveSession) -> None:
        """Derive idle time and harsh accel/brake counts from SPEED samples.

        Idle: consecutive samples below 5 km/h contribute their Δt.
        Harsh accel/brake: |Δv/Δt| above ~3.5 m/s² (≈12.6 km/h per second).

        NOTE: This currently loads all SPEED rows into Python. A future optimization
        could use SQL window functions (LAG) to compute deltas in the database, but
        that change requires test coverage to catch regressions.
        """
        if not session.started_at or not session.ended_at:
            return

        upper_keys = [k.upper() for k in SPEED_PARAM_KEYS]
        result = await self.db.execute(
            select(VehicleTelemetry.timestamp, VehicleTelemetry.value)
            .where(VehicleTelemetry.vin == session.vin)
            # Device-scoped for the same reason as the aggregates above: idle
            # seconds and harsh-event counts are derived from the SPEED series,
            # so a co-located device's samples would invent events.
            .where(VehicleTelemetry.device_id == session.device_id)
            .where(func.upper(VehicleTelemetry.param_key).in_(upper_keys))
            .where(VehicleTelemetry.timestamp >= session.started_at)
            .where(VehicleTelemetry.timestamp <= session.ended_at)
            .order_by(VehicleTelemetry.timestamp.asc())
        )
        rows = list(result.all())
        if len(rows) < 2:
            session.idle_seconds = 0
            session.harsh_accel_count = 0
            session.harsh_brake_count = 0
            return

        idle_seconds = 0.0
        harsh_accel = 0
        harsh_brake = 0
        idle_threshold_kmh = IDLE_THRESHOLD_KMH
        harsh_ms2 = 3.5  # m/s²
        # Convert km/h/s to m/s²: 1 km/h/s = 1000/3600 m/s² ≈ 0.2778
        harsh_kmh_per_s = harsh_ms2 / (1000.0 / 3600.0)

        prev_ts, prev_speed = rows[0]
        for ts, speed in rows[1:]:
            if prev_ts is None or ts is None or speed is None or prev_speed is None:
                prev_ts, prev_speed = ts, speed
                continue
            dt = (ts - prev_ts).total_seconds()
            if dt <= 0 or dt > 120:
                prev_ts, prev_speed = ts, speed
                continue
            if float(prev_speed) < idle_threshold_kmh and float(speed) < idle_threshold_kmh:
                idle_seconds += dt
            dv_dt = (float(speed) - float(prev_speed)) / dt
            if dv_dt >= harsh_kmh_per_s:
                harsh_accel += 1
            elif dv_dt <= -harsh_kmh_per_s:
                harsh_brake += 1
            prev_ts, prev_speed = ts, speed

        session.idle_seconds = int(round(idle_seconds))
        session.harsh_accel_count = harsh_accel
        session.harsh_brake_count = harsh_brake

    async def _get_param_stats_multi(
        self,
        vin: str,
        device_id: str | None,
        param_keys: list[str],
        start: datetime,
        end: datetime,
    ) -> dict[str, float | None]:
        """Get stats for a parameter during a time range, for one device.

        Accepts multiple possible param_key names and matches any of them
        (case-insensitive) to handle different WiCAN naming conventions.

        Scoped by device, not just VIN: a vehicle can carry both a WiCAN dongle
        and a Torque source, whose sessions overlap in wall-clock time, and a
        VIN-wide query let one device's samples rewrite the other's maxima.
        """
        upper_keys = [k.upper() for k in param_keys]
        result = await self.db.execute(
            select(
                func.min(VehicleTelemetry.value),
                func.max(VehicleTelemetry.value),
                func.avg(VehicleTelemetry.value),
                func.count(VehicleTelemetry.id),
            )
            .where(VehicleTelemetry.vin == vin)
            .where(VehicleTelemetry.device_id == device_id)
            .where(func.upper(VehicleTelemetry.param_key).in_(upper_keys))
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
    # Timeout Detection
    # =========================================================================

    async def check_session_timeouts(
        self,
        timeout_minutes: int = 5,
        gap_minutes: int | None = None,
        now: datetime | None = None,
    ) -> list[DriveSession]:
        """Close open sessions on either of TWO clocks, and never at last contact.

        Two clocks, because the five-minute setting is a CONNECTION-LOSS
        detector and must not double as a drive-splitter:

        ===============  ==================================  =====================
        Clock            Setting                             Measured from
        ===============  ==================================  =====================
        Drive gap        ``livelink_session_gap_minutes``     ``last_movement_at``
        Contact loss     ``livelink_session_timeout_minutes`` ``last_seen``
        ===============  ==================================  =====================

        The drive gap is checked FIRST, and its closure is final. Contact loss
        closes just as promptly -- a device that never returns must not be left
        open -- but RETAINS the pointer, so movement returning inside the gap
        reopens the same session rather than creating a second one. Without that
        distinction, movement then six minutes of silence then movement gives
        two sessions live and one on replay, for the same journey.

        A vehicle stationary but still connected is in neither state: it is
        ``stopped``, and it closes on the drive gap. So a six-minute charge, a
        fuel stop or a drive-through no longer splits a drive, while a
        twenty-minute stop still does -- which is what a person would call two
        trips. An ICE vehicle idling at a light keeps RPM and survived the old
        rule; a stationary EV reports neither speed nor RPM, so it is precisely
        the vehicle the old rule shredded.

        **Neither clock stamps ``ended_at`` from its own cutoff.** The previous
        implementation selected on ``last_seen`` and then called
        ``end_session(device, last_seen)`` -- and ``update_device_status`` sets
        ``last_seen`` on EVERY call, heartbeat included. Changing only the
        selection predicate would leave every drive's tail padded by up to one
        heartbeat interval (95 minutes, measured) and drag ``avg_speed`` toward
        zero with parked samples, re-widening the window PR #157 narrowed. Both
        clocks close at ``movement_ended_at``.

        Args:
            timeout_minutes: Contact-loss timeout.
            gap_minutes: Drive-gap threshold; read from settings when omitted.
            now: Injected clock, for tests.

        Returns:
            List of sessions that were closed.
        """
        now = self._naive(now or utc_now())
        if gap_minutes is None:
            gap_minutes = await self._gap_minutes()
        contact_cutoff = now - timedelta(minutes=timeout_minutes)
        gap_cutoff = now - timedelta(minutes=gap_minutes)
        closed_sessions = []

        # Joined to the session and filtered to OPEN ones: in the `awaiting`
        # state the pointer deliberately names a CLOSED session, and selecting
        # on the pointer alone would try to close it again on every tick.
        rows = (
            await self.db.execute(
                select(LiveLinkDevice, DriveSession)
                .join(DriveSession, DriveSession.id == LiveLinkDevice.current_session_id)
                .where(DriveSession.ended_at.is_(None))
            )
        ).all()

        for device, session in rows:
            moved_at = self._naive(
                device.last_movement_at
                or session.movement_ended_at
                or session.movement_started_at
                or session.started_at
            )
            last_seen = self._naive(device.last_seen) if device.last_seen else now

            if moved_at < gap_cutoff:
                reason, retain = "drive gap", False
            elif last_seen < contact_cutoff:
                reason, retain = "contact loss", True
            else:
                continue

            ended = await self.end_session(device, moved_at, retain_pointer=retain)
            if ended:
                closed_sessions.append(ended)
                logger.info(
                    "Closed session %d for device %s on %s at %s (last contact %s)",
                    ended.id,
                    device.device_id,
                    reason,
                    moved_at,
                    last_seen,
                )

        if closed_sessions:
            await self.db.commit()

        return closed_sessions

    # =========================================================================
    # Query Methods
    # =========================================================================

    async def get_session(self, session_id: int) -> DriveSession | None:
        """Get a session by ID."""
        result = await self.db.execute(select(DriveSession).where(DriveSession.id == session_id))
        return result.scalar_one_or_none()

    async def get_vehicle_sessions(
        self,
        vin: str,
        limit: int = 50,
        offset: int = 0,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[DriveSession]:
        """Get sessions for a vehicle."""
        query = (
            select(DriveSession)
            .where(DriveSession.vin == vin)
            .order_by(DriveSession.started_at.desc())
        )

        if start:
            query = query.where(DriveSession.started_at >= start)
        if end:
            query = query.where(DriveSession.ended_at <= end)

        query = query.offset(offset).limit(limit)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_session_count(self, vin: str) -> int:
        """Get total session count for a vehicle."""
        result = await self.db.execute(
            select(func.count(DriveSession.id)).where(DriveSession.vin == vin)
        )
        row = result.first()
        return row[0] if row else 0

    async def get_current_session(self, device: LiveLinkDevice) -> DriveSession | None:
        """Get the current active session for a device."""
        if not device.current_session_id:
            return None

        result = await self.db.execute(
            select(DriveSession).where(DriveSession.id == device.current_session_id)
        )
        return result.scalar_one_or_none()

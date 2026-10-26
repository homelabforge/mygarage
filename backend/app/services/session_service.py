"""Session service for drive session detection and management."""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import (
    ColumnElement,
    SQLColumnExpression,
    and_,
    func,
    not_,
    or_,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.livelink_device import LiveLinkDevice
from app.models.location_point import LocationPoint
from app.models.vehicle_telemetry import VehicleTelemetry
from app.services.session_boundaries import (
    BOUNDARY_ALGORITHM_MOVEMENT,
    PENDING_SOURCE_RPM,
    DriveWindow,
    MovementSignals,
    extract_signals,
    group_drives,
)
from app.utils.datetime_utils import utc_now
from app.utils.distance_counters import (
    TravelledSpan,
    is_distance_source_param_key,
    measure_travelled,
    select_distance_source,
)
from app.utils.logging_utils import sanitize_for_log
from app.utils.movement_keys import (
    is_parked_heartbeat_key,
    rpm_param_key_candidates,
    speed_param_key_candidates,
)
from app.utils.odometer_units import (
    WICAN_DEVICE_KIND,
    is_odometer_param_key,
    is_recorded_odometer_key,
)

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

#: Where a replayed sample goes (B6-12): the live state machine, the builder
#: that makes closed sessions from stored rows, or nowhere (its own closed
#: drive's late reading, which the closed-session refresh already handles).
ReplayVerdict = Literal["live", "build", "refresh"]


def _as_stored_odometer(km: float) -> float:
    """An odometer reading the way storage keeps it: whole km.

    `TelemetryService._sanitize_odometer_value` rounds every odometer key before
    the row goes in, so the builder compares the frame in hand on that scale.
    Against raw readings, a parked car at 1001.4 beat the stored 1001 on every
    frame and stretched its drive.
    """
    return float(round(km))


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


@dataclass(frozen=True)
class SessionWindow:
    """The telemetry span a session's numbers come from (R11).

    Inclusive at both ends, except a session that starts exactly where the
    same device's previous session ended: that instant is the previous one's,
    so the start goes exclusive. Touching sessions are made on purpose (both
    the live open and SD reconstruction clamp a start to the last close), and
    with both windows inclusive the shared sample counted twice.
    """

    start: datetime
    end: datetime
    start_exclusive: bool

    def covers(self, column: SQLColumnExpression[datetime]) -> ColumnElement[bool]:
        """The WHERE clause for a timestamp column inside this window."""
        lower = column > self.start if self.start_exclusive else column >= self.start
        return and_(lower, column <= self.end)


def _moved_predicate():
    """SQL for "this session has evidence the vehicle moved".

    Distance above zero, or a top speed at or above the movement floor. NULL is
    not evidence, so ``coalesce`` reads it as stationary: a session whose
    telemetry has been pruned cannot prove it was a drive, and showing every
    unprovable row defeats the filter entirely. On the data this was measured
    against, only 5 of 2,816 speed-less sessions carry any distance at all.

    Uses :data:`IDLE_THRESHOLD_KMH` rather than a literal so the list hides
    exactly what the boundary predicate calls stationary. Two definitions of
    "moving" in one subsystem is how a vehicle comes to be simultaneously idle
    and under way.
    """
    return or_(
        func.coalesce(DriveSession.distance_km, 0) > 0,
        func.coalesce(DriveSession.max_speed, 0) >= IDLE_THRESHOLD_KMH,
    )


class SessionService:
    """Everything that decides what a drive session IS, and what it says.

    Four responsibilities, in the order they appear below:

    1. **Session detection.** `handle_ecu_status_change` and the Torque
       constructor. Note that the ECU-online branch no longer opens a session
       in the default mode -- see `observe_telemetry`.
    2. **Movement-based boundaries.** The state machine: `observe_telemetry` is
       its input edge, and the device row holds its state so the MQTT
       subscriber, the HTTPS route and the scheduler all see the same thing.
    3. **Aggregates.** `refresh_aggregates` is the single derivation of a
       session's numbers; `end_session`, late-arriving telemetry, an SD-card
       pull and the repair tools all go through it, so a session summarised on
       close and one recomputed months later cannot disagree.
    4. **Timeouts and queries.** `check_session_timeouts` runs the two clocks.

    This file is long. The natural cut is section 3, which is self-contained and
    orthogonal to the boundary rules; it was left in place deliberately during
    the v3.3.0 boundary rework rather than moved in the same change.
    """

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
        start_odometer = await self._get_current_odometer(
            device.vin, device.odometer_param_key, device.kind
        )

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
        # dead after every drive.
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

        # The pointer can name a CLOSED session, awaiting a reopen. Ending it
        # again would restamp the drive at whatever time the caller passed and
        # stretch it over the parked tail. Reopening is `_reopen_awaiting`'s
        # job and letting go is the sweep's, so leave both alone.
        if session.ended_at is not None:
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
    def clear_movement_state(device: LiveLinkDevice) -> None:
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

    @classmethod
    def _awaiting_anchor(cls, session: DriveSession) -> datetime:
        """Where a closed drive's reopen window starts.

        The earlier of its movement end and its close. They agree except after
        a future-dated frame pushed `movement_ended_at` past the close, and
        measuring from that would swallow every tail sample and keep the
        pointer for good (B6-12, E-10).
        """
        moved = session.movement_ended_at
        ended = session.ended_at
        if moved is None:
            return cls._naive(ended) if ended is not None else cls._naive(session.started_at)
        if ended is None:
            return cls._naive(moved)
        return min(cls._naive(moved), cls._naive(ended))

    async def _pointed_session(self, device: LiveLinkDevice) -> DriveSession | None:
        """The session the pointer names, open or awaiting, or None.

        A pointer whose row is gone is cleared on the spot, as
        `_reopen_awaiting` always did; nothing should keep reading a dangling id.
        """
        if not device.current_session_id:
            return None
        session = (
            await self.db.execute(
                select(DriveSession).where(DriveSession.id == device.current_session_id)
            )
        ).scalar_one_or_none()
        if session is None:
            device.current_session_id = None
        return session

    @classmethod
    def _replay_verdict(
        cls, pointed: DriveSession | None, sample_at: datetime, window: timedelta
    ) -> ReplayVerdict:
        """Where a replayed sample goes (B6-12).

        A replay never opens a pointed session. It reaches the live machine only
        as the pointed session's own late sample: inside an open drive, or in
        the reopen window after an awaiting one. A sample inside an awaiting
        drive's window is that drive's late reading, and the closed-session
        refresh already recomputes it. Everything else is built into closed
        sessions by sample time. A pre-movement (contact-mode) row keeps the
        old rule whole; the contact rule owns it.
        """
        if pointed is None:
            return "build"
        if pointed.boundary_algorithm_version < BOUNDARY_ALGORITHM_MOVEMENT:
            return "live"
        if sample_at < cls._naive(pointed.started_at):
            return "build"
        if pointed.ended_at is None:
            return "live"
        anchor = cls._awaiting_anchor(pointed)
        if sample_at <= anchor:
            return "refresh"
        if sample_at - anchor <= window:
            return "live"
        return "build"

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
        marks a replay (B6-12): it never opens a pointed session and never
        writes ``last_movement_at``, which anchors every live timeout. It
        reaches this state machine only as the pointed session's own late
        sample; anything else it says is built into closed sessions by sample
        time, from the rows already stored (`_reconcile_replayed_sample`).

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

        pointed = await self._pointed_session(device)
        session = pointed if pointed is not None and pointed.ended_at is None else None

        # A replay only gets in here as the pointed session's own late sample.
        # Anything else it says is built from its stored rows, and never touches
        # the pointer or the device's evidence (B6-12).
        if not live:
            verdict = self._replay_verdict(pointed, sample_at, window)
            if verdict == "build":
                await self._reconcile_replayed_sample(
                    device, pointed, samples, signals, sample_at, gap
                )
                return None
            if verdict == "refresh":
                return None

        # Expire a stale evidence window BEFORE evaluating this batch. Without a
        # bound, an engine-on at 08:00 and a movement sample at 17:00 are still
        # "consecutive", and the session backdates nine hours of parked
        # telemetry into a drive. Two samples separated by a disconnect are not
        # consecutive in any sense that matters.
        if session is None:
            if device.pending_since is not None and (
                sample_at - self._naive(device.pending_since) > window
            ):
                self.clear_movement_state(device)
            elif device.movement_candidate_at is not None and (
                sample_at - self._naive(device.movement_candidate_at) > window
            ):
                device.movement_candidate_at = None
                device.movement_baseline_km = None

        confirmed = self._confirm_movement(
            device, signals, sample_at, session is not None, window=window
        )

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
        operating_keys = sorted(key for key in samples if not is_parked_heartbeat_key(key))
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
        *,
        window: timedelta,
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

        The confirming sample has to be from a different instant than the
        candidate. A WiCAN re-sending one frame (or a replay overlapping what
        already landed) is the same reading twice, and one reading can't
        confirm itself.

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

        candidate_at = (
            self._naive(device.movement_candidate_at)
            if device.movement_candidate_at is not None
            else None
        )
        # A candidate more than a gap NEWER than this sample isn't the one this
        # sample follows. The expiry in `observe_telemetry` only looks the other
        # way, so a replay older than a live candidate confirmed against it and
        # the drive ran to now (re-review 4, concern 1). Live frames are at most
        # 300 s apart, so this touches a live pair only under a ten-minute gap.
        if candidate_at is not None and candidate_at - sample_at > window:
            device.movement_candidate_at = None
            device.movement_baseline_km = None
            candidate_at = None

        if signals.is_above_floor:
            if candidate_at is not None:
                return sample_at != candidate_at
            device.movement_candidate_at = sample_at
            if signals.odometer_km is not None:
                device.movement_baseline_km = Decimal(str(signals.odometer_km))
            return False

        if signals.odometer_km is not None:
            if signals.speed_kmh is not None and not signals.is_above_floor:
                # 1h: the frame says the car is stopped. Its odometer is the
                # car's reading now, so it becomes the baseline, but it proves
                # nothing and opens no window: a drive that happened while we
                # weren't looking isn't a drive starting now. Odometer-only
                # frames (no speed key at all) keep the rule below.
                if device.movement_baseline_km is None or signals.odometer_km > float(
                    device.movement_baseline_km
                ):
                    device.movement_baseline_km = Decimal(str(signals.odometer_km))
                return False
            if device.movement_baseline_km is not None:
                if signals.odometer_km > float(device.movement_baseline_km):
                    return sample_at != candidate_at
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
    ) -> DriveSession | None:
        """Movement is confirmed: open, reopen or extend a session.

        None when the movement all belongs to a drive that's already closed
        (`_open_session_for_movement` declines).
        """
        session = await self._live_session(device)

        if session is None:
            session = await self._reopen_awaiting(device, sample_at, gap)
        if session is None and live:
            session = await self._reopen_recent_closed(device, sample_at, gap)
        if session is None:
            if not live:
                # A replay only gets here through a race (the pointer went
                # between the verdict and now). It opens nothing, and its
                # evidence goes with it: left behind, one live frame would
                # confirm against it (B6-12, E-9).
                self.clear_movement_state(device)
                return None
            session = await self._open_session_for_movement(device, sample_at, gap)
        if session is None:
            return None

        if session.movement_started_at is None:
            session.movement_started_at = sample_at
        # Forward only: an older replayed sample inside the drive isn't its end.
        if session.movement_ended_at is None or sample_at > self._naive(session.movement_ended_at):
            session.movement_ended_at = sample_at
        # The baseline is the live machine's: a replayed in-drive reading is
        # behind the car and would hand the next parked frame a rise (D-10).
        if live and signals.odometer_km is not None:
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

        anchor = self._awaiting_anchor(retained)
        if sample_at <= anchor:
            # Inside the drive it just closed, or before it: that's its late
            # reading, not its return (B6-12, D-4).
            return None
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

    async def _reopen_recent_closed(
        self, device: LiveLinkDevice, sample_at: datetime, gap: int
    ) -> DriveSession | None:
        """Reopen the device's latest closed drive when live movement returns inside the gap.

        `_reopen_awaiting` needs the pointer. Since B6-12 a replayed drive never
        has one, and the live tail of a drive the WiCAN drained on the way home
        (its last five minutes arrive live) would open a second session right
        after the first (D-1). The same rule by time, without the pointer. It
        also reopens a drive the ECU-offline finalizer closed, so an engine-off
        stop shorter than the gap is one drive (ruling B6-12-E2). Never another
        VIN's drive (E-1, R8), never Torque's, never a contact-mode row.
        """
        latest = (
            await self.db.execute(
                select(DriveSession)
                .where(DriveSession.device_id == device.device_id)
                .where(DriveSession.vin == device.vin)
                .where(DriveSession.ended_at.is_not(None))
                .where(DriveSession.external_session_id.is_(None))
                .where(DriveSession.boundary_algorithm_version >= BOUNDARY_ALGORITHM_MOVEMENT)
                .order_by(DriveSession.ended_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest is None:
            return None
        anchor = self._awaiting_anchor(latest)
        if not (anchor < sample_at <= anchor + timedelta(minutes=gap)):
            return None

        # Same race as the open: two ingest paths both see no pointer. Lock the
        # device row on PostgreSQL and re-read; adopt whatever won.
        if self.db.bind is not None and self.db.bind.dialect.name == "postgresql":
            claimed = (
                await self.db.execute(
                    select(LiveLinkDevice.current_session_id)
                    .where(LiveLinkDevice.id == device.id)
                    .with_for_update()
                )
            ).scalar()
            if claimed is not None and claimed != device.current_session_id:
                await self.db.refresh(device)
                adopted = await self._live_session(device)
                if adopted is not None:
                    return adopted
        try:
            async with self.db.begin_nested():
                latest.ended_at = None
                latest.duration_seconds = None
                device.current_session_id = latest.id
                await self.db.flush()
        except IntegrityError:
            adopted = await self._open_session_for_device(device.device_id)
            if adopted is None:
                raise
            device.current_session_id = adopted.id
            return adopted
        logger.info(
            "Reopened drive session %d for device %s (movement returned within the %d-minute "
            "gap of its close)",
            latest.id,
            device.device_id,
            gap,
        )
        return latest

    async def _open_session_for_movement(
        self, device: LiveLinkDevice, sample_at: datetime, gap: int
    ) -> DriveSession | None:
        """Open a session whose window keeps the whole opening burst.

        Or none, when the sample and the candidate it confirms are both at or
        before the device's last close (T4-c): that's a replay of a drive
        already closed, and the clamp below would open an empty session at
        the close. The evidence is that drive's, so it's dropped.

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
        previous_end = await self._previous_close(device.device_id)
        if previous_end is not None and all(
            self._naive(moment) <= previous_end
            for moment in (sample_at, device.movement_candidate_at)
            if moment is not None
        ):
            logger.debug(
                "Not opening a session for device %s: its movement at %s is all before "
                "the last close at %s",
                sanitize_for_log(device.device_id),
                sanitize_for_log(sample_at),
                previous_end,
            )
            self.clear_movement_state(device)
            return None

        candidates = [
            self._naive(value)
            for value in (device.pending_since, device.movement_candidate_at)
            if value is not None
        ]
        started_at = min([*candidates, sample_at])
        # A replay can confirm a newer candidate with an older sample, so the
        # span runs earliest to latest, not candidate to sample.
        movement_span = [sample_at]
        if device.movement_candidate_at is not None:
            movement_span.append(self._naive(device.movement_candidate_at))
        started_at, movement_started_at, movement_ended_at = await self.clamp_past_previous_close(
            device.device_id, started_at, min(movement_span), max(movement_span)
        )

        # Take a row lock, then RE-READ the pointer under it.
        #
        # The re-read is the whole point, and leaving it out was measured to
        # make the lock useless: MQTT and HTTPS ingest genuinely race, both read
        # a NULL `current_session_id`, and both reach here. The loser blocks on
        # the lock, but its identity-mapped `device` still holds the stale NULL,
        # so it creates anyway and takes an IntegrityError from
        # `uq_drive_sessions_open_per_device`. The index protects the DATA
        # either way -- one open session per device -- but the losing payload
        # still fails, which for a WiCAN means a dropped reading and a retry.
        #
        # With the re-read the loser adopts the winner's session and both
        # payloads succeed. `test_session_concurrency.py` asserts that neither
        # racer raises, which is the only way to tell this apart from the
        # version that merely looked correct.
        #
        # Skipped on SQLite, where FOR UPDATE compiles to nothing. SQLite's
        # single writer serialises the WRITES, not the read that precedes them,
        # so this check-then-create still races there; the partial unique
        # index is what protects the data. See app/services/vehicle_lock.py
        # for the mechanism that would serialise it, deliberately not applied
        # to the ingest path without a race test of its own.
        if self.db.bind is not None and self.db.bind.dialect.name == "postgresql":
            claimed = (
                await self.db.execute(
                    select(LiveLinkDevice.current_session_id)
                    .where(LiveLinkDevice.id == device.id)
                    .with_for_update()
                )
            ).scalar()
            if claimed is not None and claimed != device.current_session_id:
                await self.db.refresh(device)
                adopted = await self._live_session(device)
                if adopted is not None:
                    logger.info(
                        "Adopted session %d for device %s: another ingest path opened "
                        "it while this one waited on the device lock",
                        adopted.id,
                        device.device_id,
                    )
                    return adopted

        session = DriveSession(
            vin=device.vin,
            device_id=device.device_id,
            started_at=started_at,
            movement_started_at=movement_started_at,
            movement_ended_at=movement_ended_at,
            start_odometer=await self._get_current_odometer(
                device.vin, device.odometer_param_key, device.kind
            ),
            boundary_algorithm_version=BOUNDARY_ALGORITHM_MOVEMENT,
            effective_gap_minutes=gap,
        )

        # Insert inside a SAVEPOINT so losing the race is recoverable.
        #
        # The row lock above closes the window on PostgreSQL, but MyGarage runs
        # SQLite in production and there is no `FOR UPDATE` there -- two
        # concurrent ingest transactions both insert, and one takes a
        # `UNIQUE constraint failed` from `uq_drive_sessions_open_per_device`.
        # Without the savepoint that error would poison the whole ingest
        # transaction, so the payload's telemetry would be lost along with the
        # session it lost the race for.
        #
        # Adopting the winner's session is the correct outcome, not a fallback:
        # both payloads describe the same drive.
        try:
            async with self.db.begin_nested():
                self.db.add(session)
                await self.db.flush()
        except IntegrityError:
            adopted = await self._open_session_for_device(device.device_id)
            if adopted is None:
                raise
            device.current_session_id = adopted.id
            logger.info(
                "Adopted session %d for device %s: another ingest path opened it first",
                adopted.id,
                device.device_id,
            )
            return adopted

        device.current_session_id = session.id

        logger.info(
            "Opened drive session %d for %s (device %s) on confirmed movement at %s",
            session.id,
            device.vin,
            device.device_id,
            sanitize_for_log(sample_at),
        )
        return session

    async def clamp_past_previous_close(
        self,
        device_id: str,
        started_at: datetime,
        movement_started_at: datetime,
        movement_ended_at: datetime,
        *,
        exclude_id: int | None = None,
    ) -> tuple[datetime, datetime, datetime]:
        """Keep a new or backdated window from reaching into a closed session.

        Every aggregate is a window scan, so a start before the device's last
        close makes both sessions claim the same samples. Shared by the live
        open and the SD backdate of an open session (R10), so the two agree.

        Returns ``(started_at, movement_started_at, movement_ended_at)``, naive.
        """
        started_at = self._naive(started_at)
        movement_started_at = self._naive(movement_started_at)
        movement_ended_at = self._naive(movement_ended_at)
        previous_end = await self._previous_close(device_id, exclude_id=exclude_id)
        if previous_end is None:
            return started_at, movement_started_at, movement_ended_at
        started_at = max(started_at, previous_end)
        movement_started_at = max(movement_started_at, started_at)
        # The clamp can push the start past the whole replayed span.
        movement_ended_at = max(movement_ended_at, movement_started_at)
        return started_at, movement_started_at, movement_ended_at

    async def _previous_close(
        self, device_id: str, *, exclude_id: int | None = None
    ) -> datetime | None:
        """The device's latest session close, naive, or None if it never closed one.

        ``exclude_id`` leaves one closed session out: the one whose own start is
        being moved, which would otherwise clamp itself to its own end.
        """
        stmt = (
            select(func.max(DriveSession.ended_at))
            .where(DriveSession.device_id == device_id)
            .where(DriveSession.ended_at.is_not(None))
        )
        if exclude_id is not None:
            stmt = stmt.where(DriveSession.id != exclude_id)
        previous_end = (await self.db.execute(stmt)).scalar()
        return self._naive(previous_end) if previous_end is not None else None

    async def _open_session_for_device(self, device_id: str) -> DriveSession | None:
        """The device's open session, read from the DATABASE not the pointer.

        Distinct from `_live_session`, which follows `device.current_session_id`
        -- and in the race that field is exactly what is stale.
        """
        return (
            await self.db.execute(
                select(DriveSession)
                .where(DriveSession.device_id == device_id)
                .where(DriveSession.ended_at.is_(None))
            )
        ).scalar_one_or_none()

    # =========================================================================
    # Replayed samples (B6-12)
    # =========================================================================

    async def _reconcile_replayed_sample(
        self,
        device: LiveLinkDevice,
        pointed: DriveSession | None,
        samples: Mapping[str, object],
        signals: MovementSignals,
        sample_at: datetime,
        gap: int,
    ) -> None:
        """Fit one replayed sample into the device's closed drives, by sample time.

        The sample's rows are already stored, so this only decides what they
        mean for the session list. A frame that says nothing about movement does
        nothing: if it fell inside a closed window, the closed-session refresh
        picks it up. A closed drive within a gap of the sample is extended (the
        fast path). With none in reach, a frame that proves movement on its own
        fetches the device's rows around it and hands them to the builder SD
        backfill uses, which applies the live debounce, floor and gap (the slow
        path, once per new drive). Two drives in reach is a guess either way,
        so neither moves. Never the pointed session, which the verdict already
        ruled on. A frame that REPORTS a speed under the floor is a stopped car:
        it may extend a drive on its odometer, as live's open branch does, but
        it never proves one (1h, ruling B6-12-E5).
        """
        if not device.vin:
            return
        if not (signals.is_above_floor or signals.odometer_km is not None):
            return
        window = timedelta(minutes=gap)
        reports_stopped = signals.speed_kmh is not None and not signals.is_above_floor
        odometer = (
            _as_stored_odometer(signals.odometer_km) if signals.odometer_km is not None else None
        )

        in_reach = await self._closed_sessions_in_reach(device, pointed, sample_at, window)
        if len(in_reach) > 1:
            logger.info(
                "Replayed sample at %s for device %s is within reach of %d closed drives (%s); "
                "leaving them alone",
                sanitize_for_log(sample_at),
                sanitize_for_log(device.device_id),
                len(in_reach),
                ", ".join(str(s.id) for s in in_reach),
            )
            return
        if in_reach:
            await self._extend_closed_drive(
                device, pointed, in_reach[0], signals.is_above_floor, odometer, sample_at, window
            )
            return

        if reports_stopped:
            return
        if not signals.is_above_floor:
            # An odometer frame on its own: only a rise past what the device had
            # stored in the last gap is worth a window. A parked car with the
            # odometer on every frame never gets past this line (E-6).
            latest = await self._max_odometer_between(
                device.device_id, sample_at - window, sample_at, vin=device.vin, end_exclusive=True
            )
            if latest is None or odometer is None or odometer <= latest:
                return
        rows = await self._replay_window_rows(
            device.device_id, sample_at - window, sample_at + window, vin=device.vin
        )
        rows.extend(self._frame_rows(samples, sample_at))
        await self.reconstruct_sessions_from_rows(device.vin, device.device_id, rows)

    async def _closed_sessions_in_reach(
        self,
        device: LiveLinkDevice,
        pointed: DriveSession | None,
        sample_at: datetime,
        window: timedelta,
    ) -> list[DriveSession]:
        """Closed movement drives of this device and VIN within a gap of the sample.

        One index range on (device_id, started_at): a device's sessions never
        overlap, so the three latest starts before ``sample_at + gap`` are the
        only candidates, and the end-side test runs here (D-13). Never the
        pointed session, and never another VIN's (E-1).
        """
        rows = (
            (
                await self.db.execute(
                    select(DriveSession)
                    .where(DriveSession.device_id == device.device_id)
                    .where(DriveSession.vin == device.vin)
                    .where(DriveSession.ended_at.is_not(None))
                    .where(DriveSession.external_session_id.is_(None))
                    .where(DriveSession.boundary_algorithm_version >= BOUNDARY_ALGORITHM_MOVEMENT)
                    .where(DriveSession.started_at <= sample_at + window)
                    .order_by(DriveSession.started_at.desc())
                    .limit(3)
                )
            )
            .scalars()
            .all()
        )
        return [
            s
            for s in rows
            if s.ended_at is not None
            and self._naive(s.ended_at) >= sample_at - window
            and (pointed is None or s.id != pointed.id)
        ]

    async def _extend_closed_drive(
        self,
        device: LiveLinkDevice,
        pointed: DriveSession | None,
        target: DriveSession,
        above_floor: bool,
        odometer: float | None,
        sample_at: datetime,
        window: timedelta,
    ) -> None:
        """Move a closed drive's end, or its start, to a replayed sample within reach.

        ``odometer`` is the frame's reading on the stored scale (`_as_stored_odometer`).
        """
        if target.ended_at is None:
            return
        start = self._naive(target.started_at)
        end = self._naive(target.ended_at)
        if start <= sample_at <= end:
            return  # its own late reading; the closed-session refresh covers it
        if sample_at > end:
            moving = above_floor
            if not moving and odometer is not None:
                # Against the window's own highest reading, not `end_odometer`:
                # the debounced refresh can leave that behind, and a stale value
                # would read a flat odometer as a rise (D-5, E-11).
                top = await self._max_odometer_between(device.device_id, start, end, vin=target.vin)
                moving = top is not None and odometer > top
            if not moving:
                return
            target.ended_at = sample_at
            moved = self._naive_opt(target.movement_ended_at)
            target.movement_ended_at = sample_at if moved is None or sample_at > moved else moved
            target.duration_seconds = int((sample_at - start).total_seconds())
            logger.info(
                "Extended closed drive %d for device %s to %s on a replayed sample",
                target.id,
                sanitize_for_log(device.device_id),
                sanitize_for_log(sample_at),
            )
            if pointed is not None:
                await self._merge_into_pointed(device, pointed, target, window)
            return
        # Before its start: only speed proves a head; the odometer rule runs forwards.
        if not above_floor:
            return
        started_at, movement_started_at, _ = await self.clamp_past_previous_close(
            device.device_id,
            sample_at,
            sample_at,
            self._naive_opt(target.movement_ended_at) or end,
            exclude_id=target.id,
        )
        if started_at >= start:
            return
        target.started_at = started_at
        current = self._naive_opt(target.movement_started_at)
        target.movement_started_at = (
            movement_started_at if current is None else min(current, movement_started_at)
        )
        target.duration_seconds = int((end - started_at).total_seconds())
        logger.info(
            "Extended closed drive %d for device %s back to %s on a replayed sample",
            target.id,
            sanitize_for_log(device.device_id),
            sanitize_for_log(started_at),
        )

    async def _merge_into_pointed(
        self,
        device: LiveLinkDevice,
        pointed: DriveSession,
        target: DriveSession,
        window: timedelta,
    ) -> None:
        """A replayed drive whose end has crept within a gap of the pointed drive's
        start is the same drive (D-3): backdate the pointed one (R10) and drop the
        builder's row. The row goes FIRST, because the backdate clamps past the
        device's previous close and that would be this very row (E-4).
        """
        if target.ended_at is None:
            return
        p_start = self._naive(pointed.started_at)
        t_end = self._naive_opt(target.movement_ended_at) or self._naive(target.ended_at)
        if t_end >= p_start or p_start - t_end > window:
            return
        if device.current_session_id == target.id:
            logger.error(
                "Not merging session %d for device %s: it is the pointed session",
                target.id,
                sanitize_for_log(device.device_id),
            )
            return
        drive = DriveWindow(
            started_at=self._naive(target.started_at),
            movement_started_at=self._naive_opt(target.movement_started_at)
            or self._naive(target.started_at),
            movement_ended_at=t_end,
        )
        # Nothing of a WiCAN's references a movement session (location points
        # are Torque's), but the FK is ON DELETE CASCADE, so re-point rather
        # than lose one.
        await self.db.execute(
            update(LocationPoint)
            .where(LocationPoint.drive_session_id == target.id)
            .values(drive_session_id=pointed.id)
        )
        await self.db.delete(target)
        await self.db.flush()
        await self._backdate_open_session(pointed, drive)
        if pointed.ended_at is not None:
            # An awaiting drive's start moved: its duration follows, and nothing
            # else recomputes a closed drive whose window grew (E-4).
            pointed.duration_seconds = int(
                (self._naive(pointed.ended_at) - self._naive(pointed.started_at)).total_seconds()
            )
            from app.services.telemetry_service import (
                queue_session_refresh,
            )  # local: avoids a cycle

            queue_session_refresh(self.db, pointed.id)
        logger.info(
            "Merged replayed drive %d into session %d for device %s: its end came within the "
            "gap of the start",
            target.id,
            pointed.id,
            sanitize_for_log(device.device_id),
        )

    async def _max_odometer_between(
        self,
        device_id: str,
        lo: datetime,
        hi: datetime,
        *,
        vin: str,
        end_exclusive: bool = False,
    ) -> float | None:
        """The highest odometer reading the device stored for ``vin`` in a window, or None.

        Grouped by key and filtered in Python with `is_odometer_param_key`, as
        `_calculate_session_distance` does: the odometer can arrive under any
        two-hex PID prefix, which no IN list enumerates (E-11). One VIN only: a
        relinked dongle's rows from the old car say nothing about this one (E-1).
        """
        stmt = (
            select(VehicleTelemetry.param_key, func.max(VehicleTelemetry.value))
            .where(VehicleTelemetry.device_id == device_id)
            .where(VehicleTelemetry.vin == vin)
            .where(VehicleTelemetry.timestamp >= lo)
            .group_by(VehicleTelemetry.param_key)
        )
        stmt = stmt.where(
            VehicleTelemetry.timestamp < hi if end_exclusive else VehicleTelemetry.timestamp <= hi
        )
        rows = (await self.db.execute(stmt)).all()
        tops = [float(top) for key, top in rows if top is not None and is_odometer_param_key(key)]
        return max(tops) if tops else None

    async def _replay_window_rows(
        self, device_id: str, lo: datetime, hi: datetime, *, vin: str
    ) -> list[tuple[datetime, str, float]]:
        """Every row the device stored for ``vin`` between ``lo`` and ``hi``, for `group_drives`.

        Every key, not just the movement ones: the builder walks a drive's start
        back through the ignition burst to the opening odometer, and a
        movement-only fetch would lose that (D-2). One VIN, as SD backfill hands
        over: the old car's rows mustn't pull this car's drive back into its
        time (E-1).
        """
        rows = await self.db.execute(
            select(VehicleTelemetry.timestamp, VehicleTelemetry.param_key, VehicleTelemetry.value)
            .where(VehicleTelemetry.device_id == device_id)
            .where(VehicleTelemetry.vin == vin)
            .where(VehicleTelemetry.timestamp >= lo)
            .where(VehicleTelemetry.timestamp <= hi)
        )
        return [
            (self._naive(stamp), key, float(value))
            for stamp, key, value in rows.all()
            if value is not None
        ]

    @staticmethod
    def _frame_rows(
        samples: Mapping[str, object], sample_at: datetime
    ) -> list[tuple[datetime, str, float]]:
        """The frame in hand as builder rows, in case the interval thinned its own (D-16)."""
        rows: list[tuple[datetime, str, float]] = []
        for key, value in samples.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            rows.append((sample_at, key, float(value)))
        return rows

    # =========================================================================
    # Sessions built from stored rows (SD backfill, and replays since B6-12)
    # =========================================================================

    async def reconstruct_sessions_from_rows(
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
                # Never across a VIN: a relinked dongle's drives on the old car
                # aren't this one's (B6-12, E-1, R8).
                DriveSession.vin == device.vin,
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
                session.started_at = min(self._naive_opt(session.started_at), drive.started_at)
                session.ended_at = max(self._naive_opt(session.ended_at), drive.movement_ended_at)
                session.movement_started_at = min(
                    self._naive_opt(session.movement_started_at) or drive.movement_started_at,
                    drive.movement_started_at,
                )
                session.movement_ended_at = max(
                    self._naive_opt(session.movement_ended_at) or drive.movement_ended_at,
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
            window_start = self._naive_opt(session.started_at)
            window_end = self._naive_opt(session.ended_at)
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
        current_start = self._naive_opt(session.started_at)
        if current_start is None or drive.started_at >= current_start:
            return False
        started_at, movement_started_at, _ = await self.clamp_past_previous_close(
            session.device_id,
            drive.started_at,
            drive.movement_started_at,
            drive.movement_ended_at,
            exclude_id=session.id,
        )
        if started_at >= current_start:
            return False
        session.started_at = started_at
        # A contact-mode session has no movement record; don't invent one.
        current_movement = self._naive_opt(session.movement_started_at)
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
    def _naive_opt(value: datetime | None) -> datetime | None:
        return value.replace(tzinfo=None) if value is not None and value.tzinfo else value

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
        self.clear_movement_state(device)
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

        Measured from the awaiting drive's anchor (`_awaiting_anchor`), so a
        future-dated frame's movement end can't keep a pointer for good.

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
            self.clear_movement_state(device)
            changed += 1

        awaiting = (
            await self.db.execute(
                select(LiveLinkDevice, DriveSession)
                .join(DriveSession, DriveSession.id == LiveLinkDevice.current_session_id)
                .where(DriveSession.ended_at.is_not(None))
            )
        ).all()
        for device, session in awaiting:
            if now - self._awaiting_anchor(session) <= window:
                continue
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
                device, utc_now()
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

    async def _get_current_odometer(
        self, vin: str, declared_key: str | None, kind: str | None = WICAN_DEVICE_KIND
    ) -> float | None:
        """Get the current odometer reading from latest telemetry, in kilometres.

        Matching is by key *shape*, not an exact name list: the standard SAE
        J1979 key is `A6-ODOMETER`, and an exact-match list that omitted it left
        every session on a standard-PID device with no odometer and no distance.
        A device's declared ``odometer_param_key`` replaces the shape match.
        The table is per vehicle, so a Torque phone's `TORQUE_ODOMETER` sits
        beside the WiCAN's keys; the scan skips another source's own keys, so
        a WiCAN drive never starts on the phone's total (FW-A-r4a).

        The NEWEST matching row wins. A vehicle can carry two odometer keys (a
        stale `A6-ODOMETER` beside a live `ODOMETER`), and taking whichever the
        database returned first opened sessions on the stale one.

        No conversion happens here. `TelemetryService.store_telemetry`
        normalises the odometer to canonical km on the way in, so the stored
        latest value is already metric and converting again would square the
        factor. Test `test_ingest_then_session_converts_exactly_once` drives
        ingest and session together and fails if this starts converting.
        """
        from app.models.vehicle_telemetry import VehicleTelemetryLatest

        # Newest first; the key match stays in Python so it's the same
        # `is_recorded_odometer_key` odometer records are written by. The latest
        # table holds one row per key, so this reads a handful of rows.
        result = await self.db.execute(
            select(VehicleTelemetryLatest.param_key, VehicleTelemetryLatest.value)
            .where(VehicleTelemetryLatest.vin == vin)
            .order_by(
                VehicleTelemetryLatest.timestamp.desc(),
                # Ties are real (one frame can carry two odometer keys), so
                # break them the same way every time.
                VehicleTelemetryLatest.received_at.desc(),
                VehicleTelemetryLatest.param_key,
            )
        )
        for param_key, value in result.all():
            if value is not None and is_recorded_odometer_key(param_key, kind, declared_key):
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
        window = await self.telemetry_window(session)
        if window is None:
            return
        await self._calculate_session_distance(session, window)
        await self._calculate_session_aggregates(session, window)
        await self._calculate_driving_insights(session, window)

    async def telemetry_window(self, session: DriveSession) -> SessionWindow | None:
        """Decide the session's window once, for every read of its telemetry.

        `refresh_aggregates` and the session-detail route both read through it,
        so the detail page counts what the drive's figures came from (T5-a).

        One query: the latest close among the device's other sessions that
        ended at or before this one started. Only an exact match makes the
        start exclusive, so a drive's own first sample still counts. None
        while the session is open or has no start.
        """
        if not session.started_at or not session.ended_at:
            return None
        # Naive, like the column: an aware start won't bind against it on PG.
        start = self._naive(session.started_at)
        previous_end = (
            await self.db.execute(
                select(func.max(DriveSession.ended_at))
                .where(DriveSession.device_id == session.device_id)
                # Not itself: a zero-length session ends where it starts.
                .where(DriveSession.id != session.id)
                .where(DriveSession.ended_at <= start)
            )
        ).scalar()
        return SessionWindow(
            start=start,
            end=self._naive(session.ended_at),
            start_exclusive=previous_end is not None and self._naive(previous_end) == start,
        )

    async def recorded_telemetry(self, session: DriveSession) -> tuple[list[str], int]:
        """The keys a closed session recorded, sorted, and how many rows it has.

        The device's own rows inside its window, so another device on the car
        and a touching drive's shared sample stay out (T5-a). Nothing while it's
        open.
        """
        window = await self.telemetry_window(session)
        if window is None:
            return [], 0
        rows = await self.db.execute(
            select(VehicleTelemetry.param_key, func.count())
            .where(VehicleTelemetry.vin == session.vin)
            .where(VehicleTelemetry.device_id == session.device_id)
            .where(window.covers(VehicleTelemetry.timestamp))
            .group_by(VehicleTelemetry.param_key)
            .order_by(VehicleTelemetry.param_key)
        )
        counts = rows.all()
        return [key for key, _n in counts], sum(n for _key, n in counts)

    async def _calculate_session_distance(
        self, session: DriveSession, window: SessionWindow
    ) -> None:
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

        THE ODOMETER IS NOT THE ONLY DISTANCE SOURCE
        --------------------------------------------
        It used to be the only one read, which is useless on hardware whose
        odometer resolves more coarsely than a typical trip. Every distance
        source in the window is now measured and the finest one supplies
        `distance_km`, while the odometer keeps `start_odometer` / `end_odometer`
        to itself and wins ties. The measurements behind that, and the reason
        the two key sets stay disjoint, live with the rule in
        `app/utils/distance_counters.py`.
        """
        # Which keys the window holds, so the readings query below can name them
        # in an `IN` list of literals. They cannot be listed up front: the
        # standard SAE J1979 odometer key carries an arbitrary two-hex-digit PID
        # prefix (`A6-ODOMETER`) while a WiCAN autopid has none at all, and a
        # substring match would swallow `DISTANCE_TO_EMPTY` (see
        # app/utils/distance_counters.py). Grouping by key lets Python decide
        # which are distance sources while keeping any function off the indexed
        # `param_key` column.
        result = await self.db.execute(
            select(VehicleTelemetry.param_key)
            .where(VehicleTelemetry.vin == session.vin)
            # Scoped to the session's own device, not just its VIN. One vehicle
            # can carry both a WiCAN dongle and a Torque source, and
            # `resolve_torque_session` deliberately leaves `start_odometer`
            # unset so a Torque trip cannot be stamped from the co-located
            # WiCAN's odometer. Matching on VIN alone walks back through that.
            .where(VehicleTelemetry.device_id == session.device_id)
            .where(window.covers(VehicleTelemetry.timestamp))
            .group_by(VehicleTelemetry.param_key)
        )
        # A device that NAMES its odometer parameter must have that name honoured
        # here too. Without it a Torque session never gets start_odometer /
        # end_odometer stamped: Torque records only its declared key, so for an
        # undeclared one the predicate answers False forever.
        owner = (
            await self.db.execute(
                select(LiveLinkDevice.kind, LiveLinkDevice.odometer_param_key).where(
                    LiveLinkDevice.device_id == session.device_id
                )
            )
        ).first()
        kind, declared = owner if owner is not None else (None, None)

        keys = [key for (key,) in result.all()]
        # The odometer columns follow what the device records odometers by
        # (FW-A-r2, kind-aware per FW-A-r3): a WiCAN's scan, so `ODOMETER_KM`
        # stamps them, and any other kind's declared key. Which source
        # supplies `distance_km` is ranked over the same keys as before, so a
        # key newly called an odometer doesn't move a session's distance.
        odometer_keys = {key for key in keys if is_recorded_odometer_key(key, kind, declared)}
        distance_keys = {
            key
            for key in keys
            if is_distance_source_param_key(key) or is_odometer_param_key(key, declared)
        }
        source_keys = sorted(distance_keys | odometer_keys)

        if source_keys:
            travelled = await self._distance_by_source(session, window, source_keys)

            # The odometer columns are the odometer's alone, and stay a span
            # rather than a sum: they answer "what did the clock read", not
            # "how far did it move".
            odometer_spans = [travelled[key] for key in odometer_keys]
            if odometer_spans:
                session.start_odometer = min(span.low for span in odometer_spans)
                session.end_odometer = max(span.high for span in odometer_spans)

            ranked = {key: span for key, span in travelled.items() if key in distance_keys}
            best = select_distance_source(
                ranked, {key for key in distance_keys if is_odometer_param_key(key, declared)}
            )
            if best is not None:
                session.distance_km = travelled[best].distance_km
                return

        # No distance source in the window at all. A Torque trip never has
        # one -- the app reports no odometer and no distance PID -- so its
        # distance comes from the GPS breadcrumb. This lives here rather than in `end_session` so every
        # caller gets the same policy: computed only in `end_session`, a
        # Torque session's distance stayed frozen at whatever the breadcrumb
        # held on close while its speed and RPM were repaired around it.
        from app.services.location_service import LocationService  # local import avoids cycle

        points = await LocationService(self.db).get_trip_points(session.vin, session.id)
        if len(points) >= 2:
            coords = [(float(p.latitude), float(p.longitude)) for p in points]
            session.distance_km = float(LocationService.haversine_km(coords))

    async def _distance_by_source(
        self, session: DriveSession, window: SessionWindow, source_keys: Sequence[str]
    ) -> dict[str, TravelledSpan]:
        """Measure how far each distance source moved inside the session window.

        One ordered pass over only the keys the window actually holds, so the
        `IN` list is literals discovered by the caller rather than a function
        applied to the indexed `param_key` column. `uq_telemetry_dedup`
        (`device_id`, `param_key`, `timestamp`) serves both the lookup and the
        ordering, so no sort is needed on either dialect.

        The readings come back to Python rather than folding into a window
        function in SQL, which reverses the rule
        `movement_keys.speed_param_key_candidates` states for the aggregate
        reader. Measured on a full 3,262-session rebuild of the instance this
        was written for, it costs 3 ms: sessions average 9 distance-source rows
        because only source keys are fetched, never the whole window. Folding it
        into SQL would raise the worst case from 2,701 rows to 35,049.
        """
        rows = await self.db.execute(
            select(
                VehicleTelemetry.param_key,
                VehicleTelemetry.value,
            )
            .where(VehicleTelemetry.vin == session.vin)
            .where(VehicleTelemetry.device_id == session.device_id)
            .where(window.covers(VehicleTelemetry.timestamp))
            .where(VehicleTelemetry.param_key.in_(list(source_keys)))
            .order_by(VehicleTelemetry.param_key, VehicleTelemetry.timestamp)
        )

        series: dict[str, list[float]] = {}
        for key, value in rows.all():
            series.setdefault(key, []).append(float(value))

        return {key: measure_travelled(values) for key, values in series.items()}

    async def _calculate_session_aggregates(
        self, session: DriveSession, window: SessionWindow
    ) -> None:
        """Calculate aggregate statistics for a session from telemetry data."""
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
                window,
            )
            count = stats.get("count")
            if count and count > 0:
                if avg_attr:
                    setattr(session, avg_attr, stats["avg"])
                if max_attr:
                    setattr(session, max_attr, stats["max"])

    async def _calculate_driving_insights(
        self, session: DriveSession, window: SessionWindow
    ) -> None:
        """Derive idle time and harsh accel/brake counts from SPEED samples.

        Idle: consecutive samples below 5 km/h contribute their Δt.
        Harsh accel/brake: |Δv/Δt| above ~3.5 m/s² (≈12.6 km/h per second).

        NOTE: This currently loads all SPEED rows into Python. A future optimization
        could use SQL window functions (LAG) to compute deltas in the database, but
        that change requires test coverage to catch regressions.
        """
        upper_keys = [k.upper() for k in SPEED_PARAM_KEYS]
        result = await self.db.execute(
            select(VehicleTelemetry.timestamp, VehicleTelemetry.value)
            .where(VehicleTelemetry.vin == session.vin)
            # Device-scoped for the same reason as the aggregates above: idle
            # seconds and harsh-event counts are derived from the SPEED series,
            # so a co-located device's samples would invent events.
            .where(VehicleTelemetry.device_id == session.device_id)
            .where(func.upper(VehicleTelemetry.param_key).in_(upper_keys))
            .where(window.covers(VehicleTelemetry.timestamp))
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
        window: SessionWindow,
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
            .where(window.covers(VehicleTelemetry.timestamp))
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
            last_seen = self._naive(device.last_seen) if device.last_seen else now

            # A session this algorithm did not cut gets the OLD rule, whole:
            # close on contact loss, at the last contact.
            #
            # In practice that is Torque, whose boundaries come from the phone.
            # It has no movement record of any kind -- `resolve_torque_session`
            # never calls the observer, deliberately -- so the drive gap would
            # fall back to `started_at` and close an actively-uploading trip
            # fifteen minutes after it BEGAN, cutting a one-hour drive into a
            # quarter-hour session and forty-five minutes belonging to nothing.
            # `check_session_timeouts` has no `kind` filter, so without this the
            # gap clock reaches a source that was working correctly.
            if session.boundary_algorithm_version < BOUNDARY_ALGORITHM_MOVEMENT:
                if last_seen < contact_cutoff:
                    ended = await self.end_session(device, last_seen)
                    if ended:
                        closed_sessions.append(ended)
                        logger.info(
                            "Closed session %d for device %s on contact loss at %s "
                            "(pre-movement boundaries, closed at last contact)",
                            ended.id,
                            device.device_id,
                            last_seen,
                        )
                continue

            # The anchor is the later of the last LIVE movement and the session's
            # own movement end, when that end is in the past. The live anchor
            # only counts from this session's start on (a pointed session a
            # skewed clock opened early must never close before it started), and
            # a replayed tail that moved the end past the last live frame closes
            # the drive at the tail, not at the WiFi drop (B6-12, D-8). A
            # future-dated frame's end is ignored, or one bad frame would hold a
            # drive open for an hour (FW-B-r2).
            started_at = self._naive(session.started_at)
            own_end = (
                self._naive(session.movement_ended_at)
                if session.movement_ended_at is not None
                and self._naive(session.movement_ended_at) <= now
                else None
            )
            live_anchor = (
                self._naive(device.last_movement_at)
                if device.last_movement_at is not None
                and self._naive(device.last_movement_at) >= started_at
                else None
            )
            anchors = [anchor for anchor in (live_anchor, own_end) if anchor is not None]
            moved_at = (
                max(anchors)
                if anchors
                else self._naive(session.movement_started_at or session.started_at)
            )

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
        include_stationary: bool = True,
    ) -> list[DriveSession]:
        """Get sessions for a vehicle.

        ``include_stationary=False`` hides sessions with no evidence the vehicle
        moved. A parked WiCAN checks in about every 95 minutes and, under the
        pre-098 contact rule, each check-in opened a session: on the instance
        this was built against, 2,921 of 3,262 recorded sessions never moved at
        all. They cannot be rebuilt into real drives, because the telemetry that
        would prove where a drive began and ended was never captured, and they
        must not be deleted: a release that tried removed 2,700 km of genuinely
        recorded distance.

        Filters on MOVEMENT, not on ``boundary_algorithm_version``. Hiding by
        algorithm buries 341 of those same sessions in which the vehicle
        demonstrably DID move, which is real history and the user's own record
        of it. What makes a row worthless is that nothing moved, not which rule
        cut it.

        A property of the VIEW. Every row stays, the default shows all of them,
        and the caller that narrows says so explicitly.
        """
        query = (
            select(DriveSession)
            .where(DriveSession.vin == vin)
            .order_by(DriveSession.started_at.desc())
        )

        if start:
            query = query.where(DriveSession.started_at >= start)
        if end:
            query = query.where(DriveSession.ended_at <= end)
        if not include_stationary:
            query = query.where(_moved_predicate())

        query = query.offset(offset).limit(limit)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_session_count(self, vin: str, include_stationary: bool = True) -> int:
        """Total session count for a vehicle, under the same filter as the list.

        Takes ``include_stationary`` because a total that counted rows the list
        refuses to show would leave the last page of a filtered list
        permanently empty, and report a number of drives the UI never renders.
        """
        query = select(func.count(DriveSession.id)).where(DriveSession.vin == vin)
        if not include_stationary:
            query = query.where(_moved_predicate())
        result = await self.db.execute(query)
        row = result.first()
        return row[0] if row else 0

    async def get_stationary_session_count(self, vin: str) -> int:
        """How many of a vehicle's sessions show no evidence it ever moved.

        Reported alongside a filtered list so the view can name what it is
        holding back. A list showing nothing is indistinguishable from a broken
        one unless it can say why it is empty.
        """
        result = await self.db.execute(
            select(func.count(DriveSession.id))
            .where(DriveSession.vin == vin)
            .where(~_moved_predicate())
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

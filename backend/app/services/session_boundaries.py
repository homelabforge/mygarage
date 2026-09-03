"""What one batch of telemetry says about whether the vehicle is moving.

Pure functions over a single reading batch. The stateful half of the boundary
rules -- the two-sample debounce, pending drives, expiry, the two clocks -- lives
in :class:`app.services.session_service.SessionService`, because it needs rows.
Keeping the *meaning* of a batch separate from the *transitions* it triggers is
what lets the meaning be tested without a database.

A drive session used to open on contact: any sign the dongle could reach the
broker. A parked WiCAN publishes a battery-voltage heartbeat roughly every 95
minutes, and every Mirage session on 2026-09-01 began within 0.1 seconds of one,
twelve for twelve. 83% of recorded sessions were a heartbeat.

THREE SIGNALS, NOT TWO, AND RPM IS NOT ONE OF THEM ON ITS OWN
-------------------------------------------------------------
The first design said ``speed > 0 OR rpm > 0``.

*The floor.* ``> 0`` opens a session on a single noisy 1 km/h sample, and that
sample is effectively unvalidatable: ``validate_rate_of_change`` skips entirely
when the previous reading is older than ``RATE_CHECK_MAX_AGE_SECONDS = 120``,
which is exactly the parked-heartbeat case. The floor is
:data:`MOVEMENT_FLOOR_KMH`, which is the *same* constant idle accounting already
used -- not a new one, or "moving" would have had two contradictory definitions
twelve lines apart.

*The odometer.* An odometer increase proves movement even when speed arrives
under a name nothing recognises, which is the cohort that would otherwise have
no sessions at all and, worse, be erased by a reconstruction that requires
positive evidence of movement.

*RPM.* An engine turning with the vehicle stationary is a remote start, a
diagnostic session, a winter warm-up, or the eleven-minute driveway idle that was
credited with 14 km and started this rework. So RPM opens a *pending* drive
(see ``SessionService``), never a session.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.utils.movement_keys import is_rpm_param_key, is_speed_param_key
from app.utils.odometer_units import is_odometer_param_key

#: Speed at or above which the vehicle counts as moving, in km/h.
#:
#: Deliberately imported from ``session_service`` rather than defined here:
#: ``_calculate_driving_insights`` has treated ``< 5 km/h`` as not-moving for
#: idle accounting since the session code was written, and two definitions of
#: "moving" in one subsystem is how a vehicle comes to be simultaneously idle
#: and under way. ``test_session_boundaries.py`` asserts they stay equal.
MOVEMENT_FLOOR_KMH = 5.0

#: Which signal opened a pending drive. Stored in
#: ``livelink_devices.pending_source`` (VARCHAR(10)).
#:
#: Only ``rpm`` is ever written, and that is not an oversight: a pending drive
#: is by definition "the engine is on and nothing has moved yet". A sample above
#: the movement floor goes straight to the candidate/confirm path, so there is
#: no state in which speed opens a pending drive. The column is wider than one
#: value because a future third signal would land here, and because a stored
#: enum of one is indistinguishable from a boolean nobody named.
PENDING_SOURCE_RPM = "rpm"

#: Stamped on every session this algorithm cuts. 0 is the column default and
#: means "pre-098, bounded on contact", so history is not misdescribed -- but a
#: NEW session left at 0 would masquerade as history and be skipped by every
#: future reconstruction, which is why each constructor sets this explicitly.
BOUNDARY_ALGORITHM_MOVEMENT = 1


def _numeric(value: object) -> float | None:
    """``value`` as a float, or None if it is not a number.

    Telemetry values arrive as ``float | int | str | None``: DTC payloads carry
    strings, and a dropped reading is None.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


@dataclass(frozen=True)
class MovementSignals:
    """The three movement-bearing quantities in one telemetry batch.

    ``None`` means "this batch did not report it", which is different from zero:
    a batch reporting ``SPEED = 0`` says the vehicle is stopped, while a batch
    reporting no speed at all says nothing. Collapsing the two is how a
    stationary EV -- which reports neither speed nor RPM when parked -- becomes
    indistinguishable from a device that has gone quiet.
    """

    speed_kmh: float | None
    rpm: float | None
    odometer_km: float | None

    @property
    def has_any_signal(self) -> bool:
        """True if the batch reported any of the three at all.

        Used for the diagnostic in C12: a device producing telemetry across a
        window but never a movement signal is logged by name, with the keys it
        did send, rather than silently recording zero drives.
        """
        return self.speed_kmh is not None or self.rpm is not None or self.odometer_km is not None

    @property
    def is_above_floor(self) -> bool:
        """True if this batch's speed is at or above the movement floor."""
        return self.speed_kmh is not None and self.speed_kmh >= MOVEMENT_FLOOR_KMH

    @property
    def is_engine_on(self) -> bool:
        """True if the engine is turning. NOT sufficient to open a session."""
        return self.rpm is not None and self.rpm > 0


def extract_signals(samples: Mapping[str, object]) -> MovementSignals:
    """Read the movement signals out of a canonicalised telemetry batch.

    ``samples`` maps canonical param keys to values, as
    ``TelemetryService.store_telemetry`` has them after canonicalisation and
    odometer normalisation -- so ``odometer_km`` here is already canonical
    kilometres and needs no conversion.

    The highest speed in the batch wins when two keys carry it, which happens
    across a firmware change that renames a PID. Taking the max is the safe
    direction: under-reading loses a real drive, while over-reading at worst
    opens a session that a long stop would have opened anyway.
    """
    speed: float | None = None
    rpm: float | None = None
    odometer: float | None = None

    for key, raw in samples.items():
        value = _numeric(raw)
        if value is None:
            continue
        if is_speed_param_key(key):
            speed = value if speed is None else max(speed, value)
        elif is_rpm_param_key(key):
            rpm = value if rpm is None else max(rpm, value)
        elif is_odometer_param_key(key):
            odometer = value if odometer is None else max(odometer, value)

    return MovementSignals(speed_kmh=speed, rpm=rpm, odometer_km=odometer)


@dataclass(frozen=True)
class DriveWindow:
    """One drive found in a batch of replayed samples.

    ``started_at`` is the first sample of the contact burst the drive belongs
    to, which is what aggregates are computed from -- so it backdates past the
    first movement sample to keep the ignition-time readings, the opening
    odometer above all. ``movement_started_at`` and ``movement_ended_at`` are
    when the vehicle actually moved.
    """

    started_at: datetime
    movement_started_at: datetime
    movement_ended_at: datetime


def group_drives(
    samples: Sequence[tuple[datetime, str, float]],
    gap_minutes: int,
) -> list[DriveWindow]:
    """Split replayed samples into the drives they describe.

    The SD card is the only path for anything driven out of broker range, and
    ``bulk_backfill`` had never created a session: it called only a refresh that
    selects sessions which already exist and are already closed. So a whole
    drive taken away from home was recorded as nothing at all.

    Applies the SAME predicate and the SAME gap as the live path, deliberately.
    An earlier design revision scoped the gap threshold to reconstruction only,
    which meant one journey got two different answers depending on whether it
    arrived over MQTT or off an SD card.

    The debounce carries over too: a group needs either two movement timestamps
    or a genuine odometer increase. A lone above-floor sample is not a drive,
    here for the same reason as live -- except that here the consequence is
    worse, because a replay path that manufactured a session per contact burst
    would invent thousands of phantom drives out of history, and no later
    upgrade undoes that.

    Returns non-overlapping windows in chronological order. Overlap matters
    because nothing in the schema forbids it (the session time indexes are
    non-unique) and every aggregate is a window scan, so two overlapping
    sessions both claim the same samples and both report the same distance.
    """
    if not samples or gap_minutes <= 0:
        return []

    window = timedelta(minutes=gap_minutes)

    by_time: dict[datetime, dict[str, float]] = {}
    for stamp, key, value in samples:
        at = stamp.replace(tzinfo=None) if stamp.tzinfo is not None else stamp
        by_time.setdefault(at, {})[key] = value
    stamps = sorted(by_time)

    #: Movement timestamps, and which of them were proven by the odometer.
    movement: list[datetime] = []
    odometer_proven: set[datetime] = set()
    highest_odometer: float | None = None

    for at in stamps:
        signals = extract_signals(by_time[at])
        moved = signals.is_above_floor
        if signals.odometer_km is not None:
            if highest_odometer is not None and signals.odometer_km > highest_odometer:
                moved = True
                odometer_proven.add(at)
            # Track the highest seen, not the latest: SD rows can arrive out of
            # order, and a lower reading is a replay artefact rather than a
            # vehicle driving backwards.
            highest_odometer = (
                signals.odometer_km
                if highest_odometer is None
                else max(highest_odometer, signals.odometer_km)
            )
        if moved:
            movement.append(at)

    if not movement:
        return []

    groups: list[list[datetime]] = [[movement[0]]]
    for at in movement[1:]:
        if at - groups[-1][-1] <= window:
            groups[-1].append(at)
        else:
            groups.append([at])

    drives: list[DriveWindow] = []
    for group in groups:
        if len(group) < 2 and not any(at in odometer_proven for at in group):
            continue

        first_movement = group[0]
        # Walk back through the contact burst: keep absorbing earlier samples
        # while each step is inside one gap window. A larger step means the
        # device was silent, so those readings belong to a different burst.
        burst_start = first_movement
        index = stamps.index(first_movement)
        while index > 0 and burst_start - stamps[index - 1] <= window:
            index -= 1
            burst_start = stamps[index]

        # Never reach back into a drive already accounted for.
        if drives and burst_start < drives[-1].movement_ended_at:
            burst_start = drives[-1].movement_ended_at

        drives.append(
            DriveWindow(
                started_at=burst_start,
                movement_started_at=max(first_movement, burst_start),
                movement_ended_at=group[-1],
            )
        )

    return drives

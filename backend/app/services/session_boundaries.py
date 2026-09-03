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

from collections.abc import Mapping
from dataclasses import dataclass

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
PENDING_SOURCE_RPM = "rpm"
PENDING_SOURCE_SPEED = "speed"


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

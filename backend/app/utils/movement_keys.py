"""Which telemetry keys carry the signals that prove a vehicle moved.

A drive session used to open on *contact* -- any sign the dongle could reach the
broker. A parked WiCAN publishes a battery-voltage heartbeat roughly every 95
minutes, so 83% of recorded sessions were a heartbeat rather than a drive.
Opening on *movement* instead needs a reliable answer to "is this key a speed
reading?", across every naming convention the four ingest paths produce.

WHY NOT REUSE ``is_odometer_param_key``'s TREATMENT
--------------------------------------------------
That helper strips the OBD2 PID prefix and compares against a bare-name set,
which works for odometer only by coincidence: ``A6-ODOMETER`` strips to
``ODOMETER``, which *is* the bare name. Speed and RPM do not have that property.

    0D-VEHICLESPEED  strips to  VEHICLESPEED   which is NOT "SPEED"
    0C-ENGINERPM     strips to  ENGINERPM      which is NOT "ENGINE_RPM"

A faithful port would return False for exactly the PID-prefixed keys that the
standard-PID WiCAN firmware emits, so no session would open on that hardware at
all -- silently, because "no movement detected" and "key not recognised" look
identical from outside. The alias sets below are therefore explicit, and
``test_movement_keys.py`` asserts every historically-observed spelling.

Torque needs no special case: ``torque_pid_map`` maps ``k0d -> SPEED`` and
``k0c -> ENGINE_RPM``, deliberately chosen to match these names.
"""

from __future__ import annotations

from app.utils.odometer_units import bare_param_key

#: Speed aliases, with any OBD2 PID prefix stripped. ``VEHICLESPEED`` is what
#: ``0D-VehicleSpeed`` becomes; ``SPEED`` is the bare WiCAN autopid and the
#: Torque mapping. Both spellings have been observed in production.
_SPEED_BARE_KEYS = frozenset({"SPEED", "VEHICLESPEED", "VEHICLE_SPEED"})

#: RPM aliases. ``ENGINERPM`` is ``0C-EngineRPM`` stripped; ``ENGINE_RPM`` is
#: the canonical form ``canonical_param_key`` produces from ``Engine RPM``.
_RPM_BARE_KEYS = frozenset({"RPM", "ENGINERPM", "ENGINE_RPM"})


#: The standard SAE J1979 PIDs that carry these readings. Used to generate the
#: prefixed spellings for the aggregate reader's SQL ``IN`` list, so that list
#: is derived from the alias sets above rather than hand-copied beside them.
_SPEED_PID_PREFIXES = ("0D",)
_RPM_PID_PREFIXES = ("0C",)

#: Keys a PARKED vehicle publishes on its own, prefix stripped. Read through
#: :func:`is_parked_heartbeat_key`; the set is public only because
#: ``LiveLinkService`` matches it in SQL, where a Python predicate cannot go.
PARKED_HEARTBEAT_KEYS = frozenset({"BATTERY_VOLTAGE"})


def _candidates(bare_keys: frozenset[str], prefixes: tuple[str, ...]) -> list[str]:
    """Every spelling of ``bare_keys``, bare and PID-prefixed, sorted."""
    return sorted(bare_keys | {f"{p}-{k}" for p in prefixes for k in bare_keys})


def speed_param_key_candidates() -> list[str]:
    """Every speed spelling, for a SQL ``IN`` list matched against ``upper()``.

    The aggregate reader cannot call :func:`is_speed_param_key` -- it matches in
    SQL to avoid loading a window's telemetry into Python -- so it needs the set
    enumerated. Generating it here rather than writing a second list in
    ``session_service`` is what keeps "a key that can open a session" and "a key
    the aggregates can read" the same set; ``test_movement_keys.py`` asserts
    both directions.
    """
    return _candidates(_SPEED_BARE_KEYS, _SPEED_PID_PREFIXES)


def rpm_param_key_candidates() -> list[str]:
    """Every RPM spelling, for a SQL ``IN`` list matched against ``upper()``."""
    return _candidates(_RPM_BARE_KEYS, _RPM_PID_PREFIXES)


def is_speed_param_key(param_key: str) -> bool:
    """True if ``param_key`` names a road-speed reading."""
    return bare_param_key(param_key) in _SPEED_BARE_KEYS


def is_rpm_param_key(param_key: str) -> bool:
    """True if ``param_key`` names an engine-RPM reading."""
    return bare_param_key(param_key) in _RPM_BARE_KEYS


def is_parked_heartbeat_key(param_key: str) -> bool:
    """True if ``param_key`` is something a PARKED vehicle publishes on its own.

    A batch containing nothing else is a heartbeat, not a vehicle whose movement
    went unread, and the difference is the whole content of the "this device's
    movement is unreadable" warning: without it that warning fires for every
    parked dongle on every instance, which is how it came to name an entire
    fleet on the first boot after migration 098.

    A predicate rather than the bare set because both callers would otherwise
    re-derive the normalisation, and one of them already forgot the PID-prefix
    strip that every other predicate here applies.
    """
    return bare_param_key(param_key) in PARKED_HEARTBEAT_KEYS

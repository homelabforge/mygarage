"""Resolve the units a LiveLink device reports its odometer in.

Storage is metric-canonical (km). Which unit a raw reading is in comes from,
in order:

1. the device's ``LiveLinkDevice.odometer_unit``, when set: it always wins;
2. the unit the device declared for that key (this request's HTTPS ``config``,
   else its stored R12 row in ``livelink_device_units``, ``wire`` or
   ``legacy``), WiCAN only;
3. the key's shape:

    A6-ODOMETER   standard PID 0xA6, metric per SAE J1979   -> km
    ODOMETER      upstream WiCAN's name for a km odometer   -> km
    ODOMETER_MI   upstream WiCAN's name for a miles one     -> mi
    ODO, MILEAGE  any other bare key: a user autopid        -> mi (a guess)

Any other device kind reads km unless its ``odometer_unit`` says otherwise,
except ``ODOMETER_MI``, which is miles whoever sends it (Codex R1-M1): the
name says so, and the browser reads the key as canonical km.

History: `6f04e53` ("Fix/v2.26.2 currency and metric canonical") collapsed the
key shapes into `int(round(value))`, which silently killed odometer
auto-recording for every bare-autopid device — a miles value read as kilometres
lands *below* the vehicle's real odometer and the monotonic guard in
``TelemetryService._sync_odometer_from_telemetry`` drops it with no log line.
The fix guessed miles for EVERY bare key, bare ``ODOMETER`` included, which
upstream defines as km (N-1). A WiCAN that reported an odometer key before
3.10 keeps main's reading of it (km for a PID key, miles for a bare one)
through a ``legacy`` R12 row (migration 133), because its odometer records
were written in it. ``tools/repair_wican_odometer_unit.py`` fixes a key read
in the wrong unit, either way.
"""

from __future__ import annotations

import re

from app.utils.units import UnitConverter

#: Only WiCAN exposes user-defined autopids, so only WiCAN keys carry the
#: "bare key means miles" signal.
WICAN_DEVICE_KIND = "wican"

ODOMETER_UNIT_KM = "km"
ODOMETER_UNIT_MI = "mi"

#: The units a device may declare. Anything else is treated as "not set".
VALID_ODOMETER_UNITS = frozenset({ODOMETER_UNIT_KM, ODOMETER_UNIT_MI})

#: A standard OBD2 PID key is a two-digit hex PID followed by a dash, e.g.
#: "A6-ODOMETER", "0D-VEHICLESPEED". Anything without that prefix is a
#: user-named autopid.
OBD2_PID_PREFIX_RE = re.compile(r"^[0-9A-F]{2}-")


#: Odometer key names, with any OBD2 PID prefix stripped. Deliberately an exact
#: set rather than a substring scan: `21-DISTANCEMILON` and
#: `31-DISTANCESINCECODECLEAR` are trip counters, not odometers, and a loose
#: "DISTANCE" match would silently stamp a session's odometer from one of them.
_ODOMETER_BARE_KEYS = frozenset(
    {"ODOMETER", "ODOMETER_MI", "ODO", "MILEAGE", "TOTAL_DISTANCE", "DISTANCE_TOTAL"}
)

#: Upstream WiCAN's own odometer names. Every other bare key is a user autopid.
UPSTREAM_KM_ODOMETER_KEY = "ODOMETER"
UPSTREAM_MI_ODOMETER_KEY = "ODOMETER_MI"


#: How the store and record paths pick out an odometer: a SUBSTRING scan, the
#: same on main as on 3.10. Wider than `_ODOMETER_BARE_KEYS` (it takes
#: `ODOMETER_KM`, `TOTAL_ODO`), and that width is what decides which keys were
#: converted and recorded, so it's what the old-reading guard follows.
#: Migration 133 reads this too, so widening it changes what 133 does on a
#: database that hasn't upgraded yet: that needs a new migration, not an edit.
ODOMETER_NAME_PATTERNS = ("A6-", "ODOMETER", "ODO", "MILEAGE", "DISTANCE_TOTAL", "TOTAL_DISTANCE")


def is_converted_odometer_key(param_key: str, declared: str | None = None) -> bool:
    """True for a key the store converts to km and records as an odometer.

    The one answer to "which keys did main read as an odometer", used by
    migration 133, `DeviceUnitService`'s legacy guard, the tools and live
    ingest itself. ``declared`` (a device's ``odometer_param_key``) replaces
    the scan, as it always has.
    """
    if declared:
        return param_key.upper() == declared.upper()
    upper = param_key.upper()
    return any(pattern in upper for pattern in ODOMETER_NAME_PATTERNS)


def is_recorded_odometer_key(param_key: str, kind: str | None, declared: str | None = None) -> bool:
    """True for a key a device of ``kind`` converts and records as its odometer.

    The kind-aware form of `is_converted_odometer_key` (FW-A-r3). Only a
    WiCAN's store path takes the substring scan; Torque, generic MQTT and the
    presets record just the key they declare, so for them an odometer-named
    key that isn't declared is a plain reading.
    """
    if kind == WICAN_DEVICE_KIND:
        return is_converted_odometer_key(param_key, declared)
    return bool(declared) and param_key.upper() == declared.upper()


def mains_odometer_unit(param_key: str) -> str:
    """How main read a unit-less WiCAN's odometer key: a PID km, anything else mi."""
    return ODOMETER_UNIT_KM if OBD2_PID_PREFIX_RE.match(param_key.upper()) else ODOMETER_UNIT_MI


def bare_param_key(param_key: str) -> str:
    """Uppercase ``param_key`` with any two-hex-digit OBD2 PID prefix removed.

    The one normalisation every key-class predicate in this codebase applies
    before matching. Written out separately in three modules until it drifted
    into being three things that merely looked alike; a change to the prefix
    shape (three-digit PIDs, say) now has one place to land.
    """
    return OBD2_PID_PREFIX_RE.sub("", param_key.upper())


def is_odometer_param_key(param_key: str, declared: str | None = None) -> bool:
    """True if ``param_key`` is one of the exact odometer names, prefixed or bare.

    Narrower than `is_converted_odometer_key`, which is what decides whether a
    key is an odometer. This one stays only where widening would change
    behaviour nobody ruled on: movement detection (when a drive opens) and
    which source supplies a session's distance (FW-A-r2).

    ``declared`` is a device's ``odometer_param_key``. When set it REPLACES the
    name matching for that one key: the point of a declaration is that the
    device knows and we stop guessing.

    Deliberately `if declared: return ...` rather than an `or`. Widening the
    match would reintroduce exactly what the exact-set comment above rules out:
    a device that declares `TORQUE_ODOMETER` must not thereby have
    `21-DISTANCEMILON` treated as an odometer too.
    """
    if declared:
        return param_key.upper() == declared.upper()
    return bare_param_key(param_key) in _ODOMETER_BARE_KEYS


def infer_odometer_unit(param_key: str) -> str:
    """Guess a WiCAN's odometer units from the param key shape.

    ``'km'`` for a standard OBD2 PID key and for upstream's bare ``ODOMETER``,
    ``'mi'`` for ``ODOMETER_MI`` and for any other bare key (a user autopid,
    usually reading a US dash).
    """
    key = param_key.upper()
    if OBD2_PID_PREFIX_RE.match(key) or key == UPSTREAM_KM_ODOMETER_KEY:
        return ODOMETER_UNIT_KM
    return ODOMETER_UNIT_MI


def is_miles_odometer_key(param_key: str) -> bool:
    """True for ``ODOMETER_MI``, the one key that says miles for every device kind."""
    return param_key.upper() == UPSTREAM_MI_ODOMETER_KEY


#: Unit labels that mean miles, lower-cased.
_MILES_LABELS = frozenset({"mi", "mile", "miles"})


def is_miles_unit(unit: str | None) -> bool:
    """True when a free-text unit label says miles."""
    return bool(unit) and unit.strip().lower() in _MILES_LABELS


def _distance_unit(unit: str | None) -> str | None:
    """``unit`` as 'km' or 'mi', or None when it names neither."""
    if not unit:
        return None
    unit = unit.strip().lower()
    return unit if unit in VALID_ODOMETER_UNITS else None


def resolve_odometer_unit(
    param_key: str,
    device_unit: str | None,
    device_kind: str | None = None,
    key_unit: str | None = None,
) -> str:
    """Return the units to read ``param_key`` in for a device.

    An explicit, recognised ``device_unit`` always wins. Then ``key_unit``,
    the unit the device declared for this key (resolved through
    ``DeviceUnitService``), then the key-shape rules. Both of those are WiCAN
    only. Any other kind gets the metric default: Torque Pro uploads each PID
    in its default (metric) unit whatever the phone shows (B6-8, checked
    against a capture with the phone on mph and °F). ``ODOMETER_MI`` is the
    exception, miles for every kind.
    """
    unit = _distance_unit(device_unit)
    if unit:
        return unit
    if device_kind is not None and device_kind != WICAN_DEVICE_KIND:
        return ODOMETER_UNIT_MI if is_miles_odometer_key(param_key) else ODOMETER_UNIT_KM
    return _distance_unit(key_unit) or infer_odometer_unit(param_key)


def odometer_value_to_km(
    value: float,
    param_key: str,
    device_unit: str | None = None,
    device_kind: str | None = None,
    key_unit: str | None = None,
) -> float | None:
    """Convert a raw device odometer reading to kilometres.

    Conversion goes through ``UnitConverter`` so it stays Decimal-precise, per
    the metric-canonical rule that unit conversion never uses float maths.
    """
    if resolve_odometer_unit(param_key, device_unit, device_kind, key_unit) == ODOMETER_UNIT_KM:
        return float(value)
    return UnitConverter.miles_to_km(value)

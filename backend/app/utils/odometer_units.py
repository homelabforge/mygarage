"""Resolve the units a LiveLink device reports its odometer in.

Storage is metric-canonical (km), but a device's raw odometer value is only
metric if it came from the standard SAE J1979 PID. WiCAN lets a user define an
*autopid* — an arbitrary CAN expression under a name of their choosing — and on
a US-market car that expression typically reads the dash odometer, in miles.

The key shape is the only signal available on the wire, so it is the default:

    A6-ODOMETER   standard PID 0xA6, metric per SAE J1979   -> km
    ODOMETER      bare autopid, user-defined expression     -> mi

That is a heuristic about hardware, not a fact about the protocol, so
``LiveLinkDevice.odometer_unit`` overrides it per device and always wins.

History: `6f04e53` ("Fix/v2.26.2 currency and metric canonical") collapsed the
two cases into `int(round(value))`, which silently killed odometer
auto-recording for every bare-autopid device — a miles value read as kilometres
lands *below* the vehicle's real odometer and the monotonic guard in
``TelemetryService._sync_odometer_from_telemetry`` drops it with no log line.
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
_ODOMETER_BARE_KEYS = frozenset({"ODOMETER", "ODO", "MILEAGE", "TOTAL_DISTANCE", "DISTANCE_TOTAL"})


def is_odometer_param_key(param_key: str) -> bool:
    """True if ``param_key`` names an odometer, prefixed or bare."""
    return OBD2_PID_PREFIX_RE.sub("", param_key.upper()) in _ODOMETER_BARE_KEYS


def infer_odometer_unit(param_key: str) -> str:
    """Guess a device's odometer units from the param key shape.

    Returns ``'km'`` for a standard OBD2 PID key, ``'mi'`` otherwise.
    """
    return ODOMETER_UNIT_KM if OBD2_PID_PREFIX_RE.match(param_key.upper()) else ODOMETER_UNIT_MI


def resolve_odometer_unit(
    param_key: str,
    device_unit: str | None,
    device_kind: str | None = None,
) -> str:
    """Return the units to read ``param_key`` in for a device.

    An explicit, recognised ``device_unit`` always wins. Otherwise the key-shape
    heuristic applies, but ONLY for WiCAN devices: "a bare key is an autopid, so
    probably miles" is a fact about WiCAN's user-defined CAN expressions, not
    about odometers in general. Torque Pro publishes a bare ``ODOMETER`` too and
    does not report miles, so any other device kind gets the metric default.
    """
    if device_unit and device_unit.lower() in VALID_ODOMETER_UNITS:
        return device_unit.lower()
    if device_kind is not None and device_kind != WICAN_DEVICE_KIND:
        return ODOMETER_UNIT_KM
    return infer_odometer_unit(param_key)


def odometer_value_to_km(
    value: float,
    param_key: str,
    device_unit: str | None = None,
    device_kind: str | None = None,
) -> float | None:
    """Convert a raw device odometer reading to kilometres.

    Conversion goes through ``UnitConverter`` so it stays Decimal-precise, per
    the metric-canonical rule that unit conversion never uses float maths.
    """
    if resolve_odometer_unit(param_key, device_unit, device_kind) == ODOMETER_UNIT_KM:
        return float(value)
    return UnitConverter.miles_to_km(value)

"""Torque Pro PID to canonical param_key mapping, and the query-string parser.

Torque uploads OBD PIDs as `k<hex>` and its own extended PIDs as `kff<hex>`.
The common OBD PIDs map onto the canonical keys the session aggregator reads
(session_service `aggregate_mappings`), so Torque fills the same charts and
avg/max session stats as WiCAN. Every other PID goes through the shared
`canonical_param_key`, so `kff1238` is stored as `KFF1238`.

Torque sends a PID below 0x10 unpadded (`kc`) and the map is keyed padded
(`k0c`), so every one-digit PID is padded first, mapped or not, and each PID
lands on one key (#223). Torque declares a PID's unit padded (`defaultUnit0c`),
so padding is also what makes a value meet its unit.

The PIDs in GPS_PID_FIELDS become location points, not telemetry.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.utils.autopid_normalizer import canonical_param_key

# Torque `k<hex>` → canonical param_key. Targets the generic alias each
# session-aggregate mapping lists first (SPEED, ENGINE_RPM, COOLANT_TMP,
# THROTTLE, FUEL) so aggregates populate without extra config.
TORQUE_OBD_PID_MAP: dict[str, str] = {
    "k04": "ENGINE_LOAD",
    "k05": "COOLANT_TMP",
    "k0b": "INTAKE_PRESSURE",
    "k0c": "ENGINE_RPM",
    "k0d": "SPEED",
    "k0e": "TIMING_ADVANCE",
    "k0f": "INTAKE_TEMP",
    "k10": "MAF",
    "k11": "THROTTLE",
    "k1f": "RUN_TIME",
    "k2f": "FUEL",
    "k42": "CONTROL_MODULE_VOLTAGE",
    "k46": "AMBIENT_TEMP",
    "k5c": "OIL_TEMP",
    # Torque's own accumulated total ("Vehicle distance (Odometer) saved with
    # profile"), NOT an ECU read: it drifts when the phone misses trips. Mapped
    # to a stable key so it is selectable as a device's odometer_param_key
    # instead of arriving as the opaque "KFF120C".
    "kff120c": "TORQUE_ODOMETER",
}

# Readable names for Torque's own PIDs, by storage key. Names only: the key
# stays KFF1238, so a setting saved on it keeps matching (R1-M1). The
# dashboard classifies by key and unit (classifyTelemetryParam in
# frontend/src/utils/telemetryUnits.ts), never by this name.
TORQUE_PID_NAMES: dict[str, str] = {
    "KFF1201": "Instant economy (mpg)",
    "KFF1202": "Turbo boost",
    "KFF1203": "Instant economy (km/L)",
    "KFF1204": "Trip distance",
    "KFF1205": "Trip economy (mpg)",
    "KFF1206": "Trip economy (km/L)",
    "KFF1207": "Instant economy (L/100 km)",
    "KFF1208": "Trip economy (L/100 km)",
    "KFF1220": "Acceleration X",
    "KFF1221": "Acceleration Y",
    "KFF1222": "Acceleration Z",
    "KFF1223": "Acceleration total",
    "KFF1225": "Engine torque",
    "KFF1226": "Wheel horsepower",
    "KFF1238": "OBD adapter voltage",
    "KFF1239": "GPS accuracy",
    "KFF123A": "GPS satellites",
    "KFF1249": "Air-fuel ratio, measured",
    "KFF124D": "Air-fuel ratio, commanded",
    "KFF1269": "Volumetric efficiency",
    "KFF1271": "Trip fuel used",
}

# The unit each value arrives in. Torque sends a PID's default unit whatever
# the phone is set to show (#223), and the standard PIDs default to metric,
# so nothing here is converted.
TORQUE_DEFAULT_UNITS: dict[str, str] = {
    "ENGINE_LOAD": "%",
    "COOLANT_TMP": "°C",
    "INTAKE_PRESSURE": "kPa",
    "ENGINE_RPM": "rpm",
    "SPEED": "km/h",
    "TIMING_ADVANCE": "°",
    "INTAKE_TEMP": "°C",
    "MAF": "g/s",
    "THROTTLE": "%",
    "RUN_TIME": "s",
    "FUEL": "%",
    "CONTROL_MODULE_VOLTAGE": "V",
    "AMBIENT_TEMP": "°C",
    "OIL_TEMP": "°C",
    "TORQUE_ODOMETER": "km",
    "KFF1201": "mpg",
    "KFF1202": "psi",
    "KFF1203": "km/L",
    "KFF1204": "km",
    "KFF1205": "mpg",
    "KFF1206": "km/L",
    "KFF1207": "L/100km",
    "KFF1208": "L/100km",
    "KFF1220": "g",
    "KFF1221": "g",
    "KFF1222": "g",
    "KFF1223": "g",
    "KFF1225": "ft-lb",
    "KFF1226": "hp",
    "KFF1238": "V",
    "KFF1239": "m",
    "KFF1249": ":1",
    "KFF124D": ":1",
    "KFF1269": "%",
    "KFF1271": "L",
}

# Torque GPS/extended PIDs → the LocationPoint field they populate.
GPS_PID_FIELDS: dict[str, str] = {
    "kff1006": "latitude",
    "kff1005": "longitude",
    "kff1001": "speed",  # km/h, whatever the phone shows
    "kff1007": "heading",
    "kff1010": "altitude",  # metres
}
GPS_PIDS: frozenset[str] = frozenset(GPS_PID_FIELDS)

#: How Torque spells a unit, and how we do. A v8 upload sent '/' as a space
#: and '%' as a lone space, and a raw UTF-8 degree sign reaches us as 'Â°'
#: because Starlette reads the query string as latin-1.
_UNIT_SPELLINGS: dict[str, str] = {
    "°c": "°C",
    "°f": "°F",
    "kpa": "kPa",
    "kpl": "km/L",
    "l": "L",
    "l/100km": "L/100km",
}

_HEX_DIGITS = frozenset("0123456789abcdef")


def torque_unit(raw: str | None) -> str | None:
    """A unit as Torque declares it, cleaned up, or None for none."""
    if raw is None:
        return None
    if raw == " ":
        return "%"
    unit = raw.replace("Â°", "°").replace("\\xc2\\xb0", "°").replace("\\xC2\\xB0", "°")
    unit = "/".join(unit.split())
    if not unit:
        return None
    return _UNIT_SPELLINGS.get(unit.lower(), unit)[:20]


@dataclass
class TorqueReading:
    session: str | None = None
    device_id: str | None = None
    time_ms: int | None = None
    email: str | None = None
    obd: dict[str, float] = field(default_factory=dict)
    gps: dict[str, float] = field(default_factory=dict)
    default_units: dict[str, str] = field(default_factory=dict)


def _padded_pid(key: str) -> str:
    """A lowercase Torque key with a one-digit PID padded to two (`kc` -> `k0c`).

    Only a single hex digit after the `k` changes: `k11` and every `kff...`
    key are already the shape the map uses.
    """
    if len(key) == 2 and key[0] == "k" and key[1] in "0123456789abcdef":
        return f"k0{key[1]}"
    return key


def _storage_key(torque_key: str) -> str:
    """The param_key a lowercase `k<hex>` key is stored under, mapped or not."""
    key = _padded_pid(torque_key)
    return TORQUE_OBD_PID_MAP.get(key) or canonical_param_key(key)


def _to_float(raw: str) -> float | None:
    try:
        v = float(raw)
    except TypeError, ValueError:
        return None
    # Reject NaN/inf: Torque occasionally emits "NaN" for an unavailable sensor.
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def parse_torque_query(params: Mapping[str, str]) -> TorqueReading:
    """Parse a Torque Pro upload query string into a TorqueReading.

    Splits metadata (session/id/time/email), GPS PIDs (→ ``gps``), and OBD PIDs
    (→ ``obd``, canonical keys). Non-numeric / NaN / inf values are dropped.
    """
    r = TorqueReading()
    for key, raw in params.items():
        lk = key.lower()
        if lk == "session":
            r.session = raw or None
        elif lk == "id":
            r.device_id = raw or None
        elif lk in ("eml", "email"):
            r.email = raw or None
        elif lk == "time":
            r.time_ms = int(raw) if raw and raw.isdigit() else None
        elif lk in GPS_PID_FIELDS:
            val = _to_float(raw)
            if val is None:
                continue
            r.gps[GPS_PID_FIELDS[lk]] = val
        elif lk.startswith("defaultunit"):
            # Values arrive in this unit; userUnit is only what the phone shows.
            pid = lk.removeprefix("defaultunit")
            unit = torque_unit(raw)
            if pid and set(pid) <= _HEX_DIGITS and unit and f"k{pid}" not in GPS_PID_FIELDS:
                r.default_units[_storage_key(f"k{pid}")] = unit
        elif lk.startswith("k"):
            val = _to_float(raw)
            if val is None:
                continue
            r.obd[_storage_key(lk)] = val
        # other keys (Torque protocol "v", unknown metadata) are ignored
    return r

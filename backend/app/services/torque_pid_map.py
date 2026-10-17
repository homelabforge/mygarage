"""Torque Pro PID to canonical param_key mapping, and the query-string parser.

Torque uploads OBD PIDs as `k<hex>` and its own extended PIDs as `kff<hex>`.
The common OBD PIDs map onto the canonical keys the session aggregator reads
(session_service `aggregate_mappings`), so Torque fills the same charts and
avg/max session stats as WiCAN. Every other PID goes through the shared
`canonical_param_key`, so `kff1238` is stored as `KFF1238`.

Torque sends a PID below 0x10 unpadded (`kc`) and the map is keyed padded
(`k0c`), so every one-digit PID is padded first, mapped or not, and each PID
lands on one key (#223).

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

# Torque GPS/extended PIDs → the LocationPoint field they populate.
GPS_PID_FIELDS: dict[str, str] = {
    "kff1006": "latitude",
    "kff1005": "longitude",
    "kff1001": "speed",  # GPS speed (km/h in metric mode)
    "kff1007": "heading",
    "kff1010": "altitude",
}
GPS_PIDS: frozenset[str] = frozenset(GPS_PID_FIELDS)


@dataclass
class TorqueReading:
    session: str | None = None
    device_id: str | None = None
    time_ms: int | None = None
    email: str | None = None
    obd: dict[str, float] = field(default_factory=dict)
    gps: dict[str, float] = field(default_factory=dict)


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
    # Reject NaN/inf — Torque occasionally emits "NaN" for an unavailable sensor.
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
        elif lk.startswith("k"):
            val = _to_float(raw)
            if val is None:
                continue
            r.obd[_storage_key(lk)] = val
        # other keys (Torque protocol "v", unknown metadata) are ignored
    return r

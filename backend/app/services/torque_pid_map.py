"""Torque Pro PID → canonical param_key mapping + query-string parser.

Torque uploads OBD PIDs as `k<hex>` and its own extended PIDs as `kff<hex>`.
We map the common OBD PIDs onto the exact canonical param_keys the session
aggregator already matches (see session_service `aggregate_mappings`) so Torque
telemetry flows into the same charts and populates avg/max session stats.
A single-digit PID arrives either way, `k0c` or `kc`, depending on the Torque
version (#223), so it is padded to two digits before the lookup.
Unmapped PIDs pass through the shared `canonical_param_key` normalizer (the same
one every other ingest path uses) so they auto-register consistently downstream.
GPS PIDs are split off — they become location_points, never scalar telemetry.
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
    # Torque's own computed and adapter PIDs, named so the dashboard reads
    # them instead of "KFF1238". The names steer clear of the substrings the
    # frontend classifier converts on ("speed", "temp", "press", "baro",
    # "distance" with an OBD prefix): Torque sends these in whatever unit
    # the app is set to, so they must render as the plain number sent.
    "kff1201": "MPG_INSTANT",
    "kff1202": "TURBO_BOOST",
    "kff1203": "KPL_INSTANT",
    "kff1204": "TRIP_LENGTH",
    "kff1205": "TRIP_AVG_MPG",
    "kff1206": "TRIP_AVG_KPL",
    "kff1207": "L_PER_100KM_INSTANT",
    "kff1208": "TRIP_AVG_L_PER_100KM",
    "kff1220": "ACCEL_X",
    "kff1221": "ACCEL_Y",
    "kff1222": "ACCEL_Z",
    "kff1223": "ACCEL_TOTAL",
    "kff1225": "ENGINE_TORQUE",
    "kff1226": "WHEEL_HORSEPOWER",
    "kff1238": "OBD_ADAPTER_VOLTAGE",
    "kff1239": "GPS_ACCURACY",
    "kff123a": "GPS_SATELLITES",
    "kff1249": "AFR_MEASURED",
    "kff124d": "AFR_COMMANDED",
    "kff1269": "VOLUMETRIC_EFFICIENCY",
    "kff1271": "TRIP_FUEL_USED",
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
    """A lowercase Torque key with a one-digit OBD PID padded to two (`kc` -> `k0c`).

    Torque Pro 1.12 uploads mode 01 PIDs below 0x10 unpadded (`k4`, `kc`,
    `kf`), older builds padded (`k04`, `k0c`, `k0f`), and the map is keyed
    padded. Only a single hex digit after the `k` is touched: `k11` and every
    `kff...` extended PID are already the shape the map uses, and an
    unpadded key that is not in the map still falls through unchanged.
    """
    if len(key) == 2 and key[0] == "k" and key[1] in "0123456789abcdef":
        return f"k0{key[1]}"
    return key


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
            # Unmapped PIDs go through the shared canonicalizer so Torque param_keys
            # match every other ingest path (space→underscore + upper, migration 059).
            padded = _padded_pid(lk)
            canonical = (
                TORQUE_OBD_PID_MAP[padded]
                if padded in TORQUE_OBD_PID_MAP
                else canonical_param_key(lk)
            )
            r.obd[canonical] = val
        # other keys (Torque protocol "v", unknown metadata) are ignored
    return r

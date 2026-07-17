"""Torque Pro PID → canonical param_key mapping + query-string parser.

Torque uploads OBD PIDs as `k<hex>` and its own extended PIDs as `kff<hex>`.
We map the common OBD PIDs onto the exact canonical param_keys the session
aggregator already matches (see session_service `aggregate_mappings`) so Torque
telemetry flows into the same charts and populates avg/max session stats.
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
            canonical = TORQUE_OBD_PID_MAP.get(lk) or canonical_param_key(lk)
            r.obd[canonical] = val
        # other keys (Torque protocol "v", unknown metadata) are ignored
    return r

"""Normalize autopid_data from various WiCAN firmware formats to flat key-value pairs.

Supports:
- Flat format (current): {"0C-EngineRPM": 2150, "0D-VehicleSpeed": 65}
- Grouped format (community fork): {"Engine": {"0C-EngineRPM": 2150}, ...}
- Array-grouped format: [{"group": "Engine", "pids": {"0C-EngineRPM": 2150}}]
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def canonical_param_key(key: str) -> str:
    """Canonical storage form for a telemetry param key.

    UPPERCASE with spaces as underscores. This is the single canonical form
    used by all ingest paths (MQTT, HTTPS, SD backfill) and the casing-merge
    migration. Uppercase is chosen because it is reachable losslessly from any
    casing, so dedup/merge across paths is total.
    """
    return key.upper().replace(" ", "_")


#: MyGarage's own key for a code list (fd614a86). Stock WiCAN firmware never
#: sends it; a custom profile or build has to. The WiCAN parser reads this same
#: name, so renaming it here can't quietly drop codes.
DTC_KEY = "DIAGNOSTIC_TROUBLE_CODES"

# Keys whose string values should be preserved (not dropped as non-numeric)
STRING_VALUE_KEYS = frozenset({DTC_KEY})

# WiCAN emits these as autopid "params" but they are per-frame metadata, not
# vehicle telemetry: TS is a rolling 0–59999 millisecond counter and TIMESTAMP
# is the device's unix epoch. They carry no diagnostic value and flood storage
# (one truck's TS rows were 97% of its telemetry). Dropped at every ingest
# chokepoint in canonical (UPPERCASE) form. See is_telemetry_param().
NON_TELEMETRY_PARAM_KEYS = frozenset({"TS", "TIMESTAMP"})


def is_telemetry_param(canonical_key: str) -> bool:
    """True if a canonical param_key is real telemetry (not WiCAN frame metadata).

    Expects the key already in canonical form (see canonical_param_key). Used by
    every ingest path (live store_telemetry, SD-card parser) to drop the
    non-telemetry metadata params WiCAN firmware emits alongside real PIDs.
    """
    return canonical_key not in NON_TELEMETRY_PARAM_KEYS


# Ordered, conservative substring/prefix catalog mapping a token found in the
# canonical (UPPERCASE) param key to a `TelemetryValidator.PARAM_CLASS_RANGES`
# class. First match wins. A param key that matches nothing returns None from
# infer_param_class(), which leaves it unvalidated — identical to today's
# behavior for every MQTT-ingested param, so this can only ever add coverage,
# never regress it.
#
# Ordering rationale: percentage tokens are checked first (highest-confidence,
# narrowest matches: pedal/throttle/load/fuel-level keys never collide with
# anything below). Pressure is checked before temperature so a hypothetical
# future PID combining both concepts resolves to pressure. The distance
# family is last — none of its tokens collide with anything above in the
# live fixture set. Only the shortest token per class is listed (e.g. "PRES"
# alone, not "PRESSURE" too) since the shorter token is always a substring of
# the longer one — any key containing "PRESSURE" already contains "PRES", so
# the longer form would never change the match outcome.
_PARAM_CLASS_PATTERNS: tuple[tuple[str, str], ...] = (
    ("FUELTANKLEVEL", "percentage"),
    ("FUELLEVEL", "percentage"),
    ("THROTTLE", "percentage"),
    ("PEDALPOS", "percentage"),
    ("ENGINELOAD", "percentage"),
    ("RPM", "frequency"),
    ("SPEED", "speed"),
    ("PRES", "pressure"),
    ("TEMP", "temperature"),
    ("VOLT", "voltage"),
    ("A6-", "distance"),
    ("ODOMETER", "distance"),
    ("ODO", "distance"),
    ("MILEAGE", "distance"),
    ("DISTANCE", "distance"),
)


def infer_param_class(param_key: str) -> str | None:
    """Infer a conservative telemetry `param_class` from a param key.

    Normalizes the key through `canonical_param_key` first so mixed-case
    input (e.g. "2f-FuelTankLevel") infers identically to its canonical
    form. Scans `_PARAM_CLASS_PATTERNS` in order and returns the class of
    the first matching substring token, or None if nothing matches.

    Only emits classes `TelemetryValidator.PARAM_CLASS_RANGES` understands.
    A None result is never worse than today: an unset param_class already
    bypasses all range/rate-of-change validation.
    """
    canonical = canonical_param_key(param_key)
    for token, param_class in _PARAM_CLASS_PATTERNS:
        if token in canonical:
            return param_class
    return None


def normalize_autopid_data(
    raw_data: dict[str, Any] | list[Any],
) -> dict[str, float | int | str | None]:
    """Normalize autopid_data to flat key-value format.

    Args:
        raw_data: autopid_data in any supported format

    Returns:
        Flat dict of param_key -> numeric value (or string for allowlisted keys)
    """
    if isinstance(raw_data, list):
        return _normalize_array_format(raw_data)

    # Check if any values are dicts (grouped format) vs all scalar (flat format)
    has_dict_values = any(isinstance(v, dict) for v in raw_data.values())

    if not has_dict_values:
        # Already flat format
        return _filter_values(raw_data)

    # Grouped format: {"GroupName": {"param_key": value, ...}, ...}
    return _normalize_grouped_format(raw_data)


def _filter_values(data: dict[str, Any]) -> dict[str, float | int | str | None]:
    """Filter dict to numeric values and allowlisted string values."""
    result: dict[str, float | int | str | None] = {}
    for key, value in data.items():
        if value is None:
            result[key] = None
        elif isinstance(value, (int, float)):
            result[key] = value
        elif isinstance(value, str) and key in STRING_VALUE_KEYS:
            result[key] = value
        # Skip other non-numeric values
    return result


def _normalize_grouped_format(data: dict[str, Any]) -> dict[str, float | int | str | None]:
    """Flatten grouped format to flat key-value pairs."""
    result: dict[str, float | int | str | None] = {}
    for group_name, group_data in data.items():
        if isinstance(group_data, dict):
            for key, value in group_data.items():
                if value is None or isinstance(value, (int, float)):
                    result[key] = value
                elif isinstance(value, str) and key in STRING_VALUE_KEYS:
                    result[key] = value
        elif isinstance(group_data, (int, float)):
            # Mixed format — some keys are groups, some are flat values
            result[group_name] = group_data
        elif group_data is None:
            result[group_name] = None
    return result


def _normalize_array_format(data: list[Any]) -> dict[str, float | int | str | None]:
    """Flatten array-grouped format to flat key-value pairs."""
    result: dict[str, float | int | str | None] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        pids = item.get("pids", {})
        if isinstance(pids, dict):
            for key, value in pids.items():
                if value is None or isinstance(value, (int, float)):
                    result[key] = value
                elif isinstance(value, str) and key in STRING_VALUE_KEYS:
                    result[key] = value
    return result

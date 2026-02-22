"""Normalize autopid_data from various WiCAN firmware formats to flat key-value pairs.

Supports:
- Flat format (current): {"0C-EngineRPM": 2150, "0D-VehicleSpeed": 65}
- Grouped format (community fork): {"Engine": {"0C-EngineRPM": 2150}, ...}
- Array-grouped format: [{"group": "Engine", "pids": {"0C-EngineRPM": 2150}}]
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Keys whose string values should be preserved (not dropped as non-numeric)
STRING_VALUE_KEYS = frozenset({"DIAGNOSTIC_TROUBLE_CODES"})


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

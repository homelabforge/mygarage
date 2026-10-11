"""Which usage a vehicle records: distance, engine hours, or both.

The backend twin of `frontend/src/utils/usageTracking.ts`: `usage_unit` picks
the primary (anything but "hours" reads as distance) and
`secondary_usage_enabled` adds the other one.
"""

from __future__ import annotations


def tracks_distance(usage_unit: str | None, secondary_usage_enabled: bool | None) -> bool:
    """Whether the vehicle records an odometer."""
    return usage_unit != "hours" or bool(secondary_usage_enabled)


def tracks_hours(usage_unit: str | None, secondary_usage_enabled: bool | None) -> bool:
    """Whether the vehicle records engine hours."""
    return usage_unit == "hours" or bool(secondary_usage_enabled)

"""Turn a timezone setting into a zone, with the fallback chain.

A leaf on purpose: no app.database, no config, so the offline tools can
resolve the household zone of whatever database they were pointed at.
``app.utils.household_time`` re-exports :func:`resolve_zone`.
"""

import logging
import os
from zoneinfo import ZoneInfo

import tzlocal

from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

# One WARNING per distinct bad value, not per request.
_warned_values: set[str] = set()


def _valid_zone(value: str | None, source: str) -> ZoneInfo | None:
    """Return the zone for a candidate IANA name, or None (warning once) if unusable."""
    if not value:
        return None
    try:
        return ZoneInfo(value)
    except Exception:
        if value not in _warned_values:
            _warned_values.add(value)
            logger.warning("Ignoring invalid timezone %s from %s", sanitize_for_log(value), source)
        return None


def resolve_zone(row_value: str | None) -> ZoneInfo:
    """Effective zone from a settings-row value and the fallback chain.

    Order: the row, ``MYGARAGE_TIMEZONE`` (presence in the environment, not
    the config default), the container's local zone via tzlocal, UTC.
    """
    zone = _valid_zone(row_value, "the timezone setting")
    if zone is not None:
        return zone
    if "MYGARAGE_TIMEZONE" in os.environ:
        zone = _valid_zone(os.environ["MYGARAGE_TIMEZONE"], "MYGARAGE_TIMEZONE")
        if zone is not None:
            return zone
    try:
        local_name = tzlocal.get_localzone_name()
    except Exception:
        local_name = None
    zone = _valid_zone(local_name, "the container's local zone")
    if zone is not None:
        return zone
    return ZoneInfo("UTC")

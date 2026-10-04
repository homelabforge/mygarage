"""One household calendar day, driven by the Timezone setting.

A calendar date is the household's, not the server's. Every server-side
"today" goes through :func:`household_today`, whose zone is read per
request (an app-level dependency) and per scheduled job, never cached
across them, so every writer of the ``timezone`` settings row is covered
without invalidation code. ``utc_now()`` stays the source for timestamps,
which remain naive UTC.
"""

import logging
import os
from contextvars import ContextVar
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import tzlocal
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.settings import Setting
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

TIMEZONE_SETTING_KEY = "timezone"
# Computed, served from /settings/public, never stored (plan 4.4).
EFFECTIVE_TIMEZONE_KEY = "effective_timezone"

household_zone_var: ContextVar[ZoneInfo | None] = ContextVar("household_zone", default=None)

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


async def load_household_zone(db: AsyncSession) -> ZoneInfo:
    """Read the timezone row, resolve it, and set the context variable."""
    row_value = await db.scalar(select(Setting.value).where(Setting.key == TIMEZONE_SETTING_KEY))
    zone = resolve_zone(row_value)
    household_zone_var.set(zone)
    return zone


def household_zone() -> ZoneInfo:
    """The zone loaded for this request or job, else the fallback chain.

    The fallback covers code running outside a request or job, such as
    startup and tests.
    """
    zone = household_zone_var.get()
    return zone if zone is not None else resolve_zone(None)


def household_date(timestamp: datetime) -> date:
    """The household day of a stored timestamp. A naive one is UTC, which is how
    every timestamp column here is written.

    One exception: on PostgreSQL a ``server_default=func.now()`` column is
    written in the session's time zone. That is UTC unless the server's
    ``timezone`` setting says otherwise (CI's is UTC). On a non-UTC server an
    evening-created row can land on the next day here.
    """
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(household_zone()).date()


def household_today() -> date:
    """The household's calendar date right now."""
    return datetime.now(household_zone()).date()


# Liveness endpoints stay database-free: the Docker HEALTHCHECK hits
# /health, and a locked SQLite file or an exhausted PostgreSQL pool must
# not report a live HTTP process dead. None of them uses a calendar date.
LIVENESS_PATHS = frozenset({"/health", "/healthz", "/api/health"})


async def household_zone_dependency(request: Request, db: AsyncSession = Depends(get_db)) -> None:
    """App-level dependency: load the zone with the request's own session.

    FastAPI de-duplicates ``get_db``, so a route that already opens it adds
    one indexed select and no extra connection. Liveness paths are exempt
    (see LIVENESS_PATHS); the session is created lazily and never connects
    for them.
    """
    if request.scope.get("path") in LIVENESS_PATHS:
        return
    await load_household_zone(db)

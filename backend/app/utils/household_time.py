"""One household calendar day, driven by the Timezone setting.

A calendar date is the household's, not the server's. Every server-side
"today" goes through :func:`household_today`, whose zone is read per
request (an app-level dependency) and per scheduled job, never cached
across them, so every writer of the ``timezone`` settings row is covered
without invalidation code. ``utc_now()`` stays the source for timestamps,
which remain naive UTC.
"""

from contextvars import ContextVar
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.settings import Setting

# The resolver lives in a leaf module so the offline tools can use it without
# pulling in the database and config.
from app.utils.zone_resolve import resolve_zone as resolve_zone

TIMEZONE_SETTING_KEY = "timezone"
# Computed, served from /settings/public, never stored (plan 4.4).
EFFECTIVE_TIMEZONE_KEY = "effective_timezone"

household_zone_var: ContextVar[ZoneInfo | None] = ContextVar("household_zone", default=None)


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


def household_datetime(timestamp: datetime) -> datetime:
    """A stored timestamp as an aware time on the household's clock.

    A naive one is UTC, like :func:`household_date` says.
    """
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(household_zone())


def household_date(timestamp: datetime) -> date:
    """The household day of a stored timestamp. A naive one is UTC, which is how
    every timestamp column here is written.

    That holds on PostgreSQL too: ``func.now()`` stamps land in the session's
    zone, and every session is pinned to UTC (``app.utils.pg_session``).
    Migration 134 converted what a non-UTC server had already written to the
    server-only columns, unless it couldn't trust that zone (it warns and skips
    then).
    """
    return household_datetime(timestamp).date()


def household_wall_clock_to_utc(value: datetime) -> datetime:
    """A time the user typed, as the naive UTC every stored stamp uses.

    A naive value is the household's wall clock (a form's date and time); an
    aware one already says its zone.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=household_zone())
    return value.astimezone(UTC).replace(tzinfo=None)


def household_day_utc_bounds(day: date) -> tuple[datetime, datetime]:
    """A household day as its naive UTC window, start included, end not.

    A DST day runs 23 or 25 hours, and a stamp at local midnight belongs to the
    day it starts.
    """
    start = household_wall_clock_to_utc(datetime.combine(day, datetime.min.time()))
    end = household_wall_clock_to_utc(
        datetime.combine(day + timedelta(days=1), datetime.min.time())
    )
    return start, end


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

"""Datetime utilities for database compatibility."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """
    Get current UTC time as a naive datetime.

    Returns a timezone-naive datetime representing the current UTC time.
    This is compatible with both SQLite and PostgreSQL TIMESTAMP columns.

    Using naive UTC datetimes avoids the 'can't subtract offset-naive
    and offset-aware datetimes' error with PostgreSQL asyncpg driver.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def to_naive_utc(value: datetime) -> datetime:
    """The UTC wall clock of `value`, naive.

    Aware values are converted; naive values are returned unchanged, because
    MyGarage stores naive UTC everywhere (see `utc_now`).
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)

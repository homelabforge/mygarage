"""Resolve which database a maintenance tool should operate on.

Shared by the raw-SQL repair tools. Each of them previously did

    engine = create_engine(f"sqlite:///{args.db}")

which is wrong on a PostgreSQL instance in the worst way: SQLAlchemy creates an
empty SQLite file at the given path and the tool then fails with
`no such table: livelink_devices`, so the operator sees a missing-table error
rather than "this tool cannot reach your database". PostgreSQL is a supported,
CI-tested deployment, so those instances had no repair path at all.

`--db` now accepts three forms:

* a **path** (`/data/mygarage.db`) -- the form the published upgrade note uses,
  kept working deliberately;
* a **URL** (`postgresql+asyncpg://...`), converted to the sync driver;
* **omitted**, falling back to the app's own configured database, which is the
  right answer when the tool runs inside the container.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from app.utils.db_url import to_sync_url

#: A URL scheme: letters, digits, +/-/. then "://". Requiring the slashes keeps
#: a Windows-style path ("C:/data/mygarage.db") from being read as a scheme.
_URL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")

#: Dialects the tools' raw SQL is written against. Anything else is refused by
#: name rather than failing later inside a statement.
_SUPPORTED_DIALECTS = ("sqlite", "postgresql")


def resolve_sync_url(db_arg: str | None) -> str:
    """Return the sync SQLAlchemy URL a tool should connect with.

    Args:
        db_arg: The value of ``--db``: a filesystem path, a SQLAlchemy URL, or
            None to use the app's configured database.

    Returns:
        A sync-driver SQLAlchemy URL.

    Raises:
        ValueError: If the resolved URL names a dialect these tools do not
            support, or if the configured database URL is empty.
    """
    if db_arg is None:
        from app.config import settings

        url = to_sync_url(settings.database_url)
    elif _URL_SCHEME_RE.match(db_arg):
        url = to_sync_url(db_arg)
    else:
        # A bare path. Three slashes then the path: an absolute path therefore
        # yields the four-slash form SQLAlchemy expects.
        url = f"sqlite:///{db_arg}"

    if not url.startswith(_SUPPORTED_DIALECTS):
        dialect = url.split("://", 1)[0]
        raise ValueError(
            f"unsupported database dialect {dialect!r}; "
            f"these tools support {' and '.join(_SUPPORTED_DIALECTS)}"
        )
    return url


def as_date(value: object) -> date:
    """Return a ``date`` for whatever the driver gave back for a DATE column.

    SQLite has no date type: both a ``DATE`` column and ``date(timestamp)`` come
    back as ``str``. psycopg2 adapts PostgreSQL ``DATE`` to ``datetime.date``,
    and ``date.fromisoformat`` raises ``TypeError`` on one of those. The tools
    run on both dialects, so they must not assume either representation.

    Args:
        value: A ``date``, a ``datetime``, or an ISO-8601 date string.

    Returns:
        The corresponding ``date``.

    Raises:
        ValueError: If ``value`` is None, or is a string that is not a date.
            Null is refused rather than tolerated: a null grouping key would
            collapse every null row into one fabricated day.
    """
    if value is None:
        raise ValueError("expected a date, got null")
    # datetime is a subclass of date, so narrow it before the isinstance below.
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))

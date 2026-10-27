"""Pin PostgreSQL sessions to UTC.

Every DateTime column is naive UTC, but `func.now()` defaults (`server_default`,
`onupdate`) are cast to naive time in the SESSION's zone. A server running any
other zone (a `TZ` on the container is enough) stores those columns hours off
(RD-6). So each PG engine pins its sessions here.

The two drivers need different mechanics:

- asyncpg (the app engine) ignores `PGTZ`/`PGOPTIONS` and takes the server's
  zone, so the pin rides in as a startup setting through `server_settings`.
- psycopg2 (migration runner, tools) honours `PGTZ`/`options`, so the pin is a
  `connect` event running `SET TIME ZONE 'UTC'`, which wins over either.

SQLite has no session zone (`CURRENT_TIMESTAMP` is UTC), so the factories here
hand SQLite URLs straight through.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

#: The zone every pinned session runs in.
SESSION_TIME_ZONE = "UTC"


def asyncpg_connect_args(connect_args: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return asyncpg ``connect_args`` with the session zone pinned to UTC.

    Merges into whatever the caller already passes, ``server_settings`` included
    (a test that sets ``search_path`` there keeps it). A ``timezone`` already in
    ``server_settings`` is overridden: the pin is the point.

    Args:
        connect_args: Existing ``connect_args`` for ``create_async_engine``, or None.

    Returns:
        A new dict; the input is not modified.
    """
    merged = dict(connect_args or {})
    server_settings = dict(merged.get("server_settings") or {})
    server_settings["timezone"] = SESSION_TIME_ZONE
    merged["server_settings"] = server_settings
    return merged


def _set_session_utc(dbapi_connection: Any, connection_record: Any) -> None:
    """Run ``SET TIME ZONE 'UTC'`` on a fresh psycopg2 connection.

    psycopg2 opens a transaction on the first statement, so a plain SET would be
    undone when the pool rolls that transaction back. Autocommit makes it stick
    for the whole session (SQLAlchemy's documented search_path pattern).
    """
    autocommit = dbapi_connection.autocommit
    dbapi_connection.autocommit = True
    try:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"SET TIME ZONE '{SESSION_TIME_ZONE}'")
        finally:
            cursor.close()
    finally:
        dbapi_connection.autocommit = autocommit


def pin_psycopg2_engine(engine: Engine) -> Engine:
    """Pin every connection a psycopg2 engine opens to UTC.

    Attach it before the engine hands out its first connection: a connection
    already in the pool never sees the listener. Calling it twice is harmless,
    SQLAlchemy skips a listener that's already registered.

    Args:
        engine: A sync engine on ``postgresql+psycopg2``.

    Returns:
        The same engine, for chaining.

    Raises:
        ValueError: If the engine isn't psycopg2. A pin that quietly did nothing
            would look exactly like a working one.
    """
    if engine.dialect.name != "postgresql" or engine.dialect.driver != "psycopg2":
        raise ValueError(
            f"pin_psycopg2_engine needs postgresql+psycopg2, "
            f"got {engine.dialect.name}+{engine.dialect.driver}"
        )
    event.listen(engine, "connect", _set_session_utc)
    return engine


def _pg_driver(url: str | URL) -> str | None:
    """The driver name for a PostgreSQL URL, or None for any other backend."""
    parsed = make_url(url)
    return parsed.get_driver_name() if parsed.get_backend_name() == "postgresql" else None


def create_utc_engine(url: str | URL, **kwargs: Any) -> Engine:
    """``create_engine``, with PostgreSQL sessions pinned to UTC.

    A psycopg2 URL gets the ``connect`` listener; SQLite passes through as is.

    Raises:
        ValueError: For a PostgreSQL driver other than psycopg2, which this
            can't pin.
    """
    driver = _pg_driver(url)
    if driver is None:
        return create_engine(url, **kwargs)
    if driver != "psycopg2":
        raise ValueError(f"can't pin a sync postgresql+{driver} engine; use psycopg2")
    return pin_psycopg2_engine(create_engine(url, **kwargs))


def create_utc_async_engine(url: str | URL, **kwargs: Any) -> AsyncEngine:
    """``create_async_engine``, with PostgreSQL sessions pinned to UTC.

    An asyncpg URL gets the zone merged into ``connect_args``; SQLite passes
    through as is.

    Raises:
        ValueError: For a PostgreSQL driver other than asyncpg, which this
            can't pin.
    """
    driver = _pg_driver(url)
    if driver is None:
        return create_async_engine(url, **kwargs)
    if driver != "asyncpg":
        raise ValueError(f"can't pin an async postgresql+{driver} engine; use asyncpg")
    kwargs["connect_args"] = asyncpg_connect_args(kwargs.get("connect_args"))
    return create_async_engine(url, **kwargs)

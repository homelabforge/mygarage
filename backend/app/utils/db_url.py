"""Convert an async SQLAlchemy URL to the sync driver equivalent.

The app runs on async drivers (`asyncpg`, `aiosqlite`), but two things need a
sync engine: the migration runner, and the maintenance tools under
`backend/tools/`. This conversion was written inline in `init_db` and nowhere
else, so the tools each hardcoded `sqlite:///{path}` instead. On a PostgreSQL
instance that silently created an empty SQLite file and then failed with
`no such table`, leaving PostgreSQL deployments with no repair path.

Matching is anchored to the scheme. The original inline version used an
unanchored substring test, which would also rewrite a driver name appearing in
a password.
"""

from __future__ import annotations

#: Async driver scheme -> the sync driver the migration runner and tools use.
_ASYNC_TO_SYNC: tuple[tuple[str, str], ...] = (
    ("postgresql+asyncpg", "postgresql+psycopg2"),
    ("sqlite+aiosqlite", "sqlite"),
)


def to_sync_url(url: str) -> str:
    """Return ``url`` with any async driver replaced by its sync counterpart.

    Idempotent: a URL that already names a sync driver is returned unchanged,
    so callers may apply it without first checking.

    Args:
        url: A SQLAlchemy database URL, async or sync.

    Returns:
        The same URL with a sync driver.

    Raises:
        ValueError: If ``url`` is empty or whitespace. Passing one on to
            ``create_engine`` produces a failure that names neither the caller
            nor the missing configuration.
    """
    if not url or not url.strip():
        raise ValueError("database URL is empty; nothing to connect to")

    for async_scheme, sync_scheme in _ASYNC_TO_SYNC:
        if url.startswith(async_scheme):
            return sync_scheme + url[len(async_scheme) :]
    return url

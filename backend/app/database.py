"""Database configuration and session management."""

import logging
from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)


def is_sqlite_url(url: str) -> bool:
    """Whether a database URL is SQLite, by its dialect.

    A substring test took a PostgreSQL URL with "sqlite" in its password or database name for SQLite.
    """
    return make_url(url).get_backend_name() == "sqlite"


# Create async engine with database-specific configuration
# SQLite: aiosqlite pools file connections (AsyncAdaptedQueuePool); the pool settings below are PostgreSQL's
# PostgreSQL/MySQL: Connection pooling settings apply
is_sqlite = is_sqlite_url(settings.database_url)


def _sqlite_connection_pragmas(dbapi_connection, connection_record) -> None:
    """Per-connection SQLite pragmas (runs once per new pooled connection).

    - journal_mode=WAL: concurrent readers + a single writer without
      reader/writer blocking; synchronous=NORMAL is durable and fast under WAL.
    - foreign_keys=ON: SQLite ships with FK enforcement OFF per connection.
      Without it every declared ``ON DELETE CASCADE`` is decorative and bulk
      deletes silently orphan child rows (vehicle delete orphaned all child
      tables until v2.30.1). PG enforces FKs unconditionally; this aligns the
      SQLite engine with the behavior the models already declare.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def configure_sqlite_engine(async_engine) -> None:
    """Attach the standard SQLite pragmas to an async engine.

    Exported so the test suite can configure its own engine identically to
    production — FK-enforcement behavior must not differ between the two.
    """
    event.listens_for(async_engine.sync_engine, "connect")(_sqlite_connection_pragmas)


def sqlite_database_path(url: URL) -> Path | None:
    """The file a SQLite URL opens, as the engine sees it: decoded, and None for in-memory.

    Not for `uri=true` URLs (the database part is then a URI, not a path); no deployment uses one.
    """
    if url.get_backend_name() != "sqlite":
        return None
    return Path(url.database) if url.database and url.database != ":memory:" else None


if is_sqlite:
    # Tune for concurrent writers so the MQTT ingest + scheduler + request
    # paths don't raise "database is locked":
    #   busy_timeout (via connect_args "timeout") makes a writer WAIT up to 30s for
    #   the lock instead of erroring immediately. aiosqlite blocks in its worker
    #   thread, so the event loop is not stalled.
    # Transactions stay under the pysqlite driver's legacy control, which
    # issues an implicit BEGIN only before INSERT, UPDATE or DELETE. A
    # SAVEPOINT issued with no transaction open starts one of its own and its
    # RELEASE commits it, so a `begin_nested()` block that runs first commits
    # its writes on exit, beyond the reach of a later rollback. Code that must
    # stay all-or-nothing across such savepoints opens the transaction first:
    # every import route takes `lock_vehicle_for_write` (a BEGIN IMMEDIATE on
    # SQLite) before its first write for exactly this reason.
    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        future=True,
        # A failed statement's message names its bound values, and the error
        # handlers log that message: a failed settings write would log the secret.
        hide_parameters=True,
        connect_args={"timeout": 30},
    )
    configure_sqlite_engine(engine)

    logger.info("Database engine created for SQLite (WAL, busy_timeout=30s, foreign_keys=ON)")
else:
    # PostgreSQL/MySQL: Use connection pooling for production
    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        future=True,
        hide_parameters=True,  # Bound values stay out of error messages and logs, as above
        pool_size=5,  # Maintain 5 connections in the pool
        max_overflow=10,  # Allow up to 10 additional connections if needed
        pool_timeout=30,  # Wait up to 30 seconds for a connection
        pool_recycle=3600,  # Recycle connections every hour
        pool_pre_ping=True,  # Test connections before use to catch stale connections
    )
    logger.info("Database engine created with connection pooling")

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


async def get_db() -> AsyncGenerator[AsyncSession]:
    """
    Dependency function that yields database sessions.

    Route handlers are responsible for calling commit() or rollback() explicitly.
    This provides better transaction control and avoids double-commits.

    Usage:
        @app.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            # ... do work ...
            await db.commit()  # Explicit commit
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            # Note: No auto-commit here - handlers must commit explicitly
            # This prevents double-commit issues and gives handlers full control
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def get_db_context():
    """
    Context manager for database sessions outside of request context.

    Usage:
        async with get_db_context() as db:
            # use db here
    """
    return AsyncSessionLocal()


async def init_db():
    """Initialize database tables and run migrations."""
    async with engine.begin() as conn:
        logger.info("Creating database tables...")
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created successfully")

    # Run migrations using the migration runner
    logger.info("Running database migrations...")
    try:
        # Convert async database URL to sync for migrations. Shared with the
        # maintenance tools under backend/tools/, which need the same mapping.
        from app.utils.db_url import to_sync_url

        sync_url = to_sync_url(settings.database_url)

        # Import and run migration runner
        from app.migrations.runner import run_migrations

        migrations_dir = Path(__file__).parent / "migrations"

        run_migrations(sync_url, migrations_dir)

    except Exception as e:
        logger.error("Migration error: %s", e)
        import traceback

        traceback.print_exc()
        # If the failing migration set FATAL = True, the runner annotates the
        # raised exception with __migration_fatal__. Re-raise so the app does
        # NOT serve requests against a half-migrated schema. Migration 053
        # (metric-canonical storage) opts in to this behaviour.
        if getattr(e, "__migration_fatal__", False):
            raise
        # Otherwise: log-and-continue (preserves the historical behaviour for
        # additive migrations that are safe to run alongside the old schema).

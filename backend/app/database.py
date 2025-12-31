"""Database configuration and session management."""

from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings
import logging

logger = logging.getLogger(__name__)

# Create async engine with database-specific configuration
# SQLite: Uses NullPool by default (pool settings ignored) - appropriate for async SQLite
# PostgreSQL/MySQL: Connection pooling settings apply
is_sqlite = "sqlite" in settings.database_url.lower()

if is_sqlite:
    # SQLite async: No pool configuration needed (uses NullPool automatically)
    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        future=True,
    )
    logger.info("Database engine created for SQLite (NullPool)")
else:
    # PostgreSQL/MySQL: Use connection pooling for production
    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        future=True,
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


async def get_db() -> AsyncGenerator[AsyncSession, None]:
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
    import os
    from pathlib import Path

    async with engine.begin() as conn:
        logger.info("Creating database tables...")
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created successfully")

    # Run migrations using the migration runner
    logger.info("Running database migrations...")
    try:
        # Create synchronous engine for migrations
        data_dir = Path(os.getenv("DATA_DIR", "/data"))
        database_path = data_dir / "mygarage.db"
        database_url = f"sqlite:///{database_path}"

        # Import and run migration runner
        from app.migrations.runner import run_migrations

        migrations_dir = Path(__file__).parent / "migrations"

        run_migrations(database_url, migrations_dir)

    except Exception as e:
        logger.error("Migration error: %s", e)
        import traceback

        traceback.print_exc()
        # Don't fail startup - log error and continue

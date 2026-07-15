"""Add time format preference (12h/24h) to user settings.

Adds a per-user 12-hour vs 24-hour clock display preference. Display-only —
does not affect stored timestamps (already canonical). Mirrors migration 016
(unit_preference).

FATAL: the ``User`` model declares ``time_format`` as a non-nullable column and
reads it on every auth path. The migration runner log-and-continues on
non-FATAL failure (``database.py``; there is no ``strict_migrations``
enforcement), so a silent failure would boot the app against a missing column.
Halting startup is the correct behavior for a column the model hard-depends on.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

FATAL = True


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None):
    """Add time_format column to users table (default '12h')."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        inspector = inspect(engine)
        print("Adding time format preference support...")

        existing_columns = {col["name"] for col in inspector.get_columns("users")}

        if "time_format" in existing_columns:
            print("  → time_format column already exists, skipping migration")
            return

        # Add time_format column (default: 12h). Works on both SQLite and PostgreSQL.
        conn.execute(text("ALTER TABLE users ADD COLUMN time_format VARCHAR(10) DEFAULT '12h'"))
        print("  ✓ Added time_format column to users table")

        # Backfill any existing users to 12h.
        result = conn.execute(
            text("UPDATE users SET time_format = '12h' WHERE time_format IS NULL")
        )
        print(f"  ✓ Set {result.rowcount} existing user(s) to 12h time format")

        print("\n✓ Time format migration completed successfully")


def downgrade():
    """Rollback not supported."""
    print("Downgrade not supported for ALTER TABLE ADD COLUMN")


if __name__ == "__main__":
    upgrade()

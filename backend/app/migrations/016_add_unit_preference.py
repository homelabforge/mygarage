"""Add unit preference to user settings.

This migration adds support for per-user unit system preferences (imperial vs metric).
All data remains stored in imperial units; this setting controls display conversion only.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None):
    """Add user_unit_preference column to users table."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        inspector = inspect(engine)
        print("Adding unit preference support...")

        existing_columns = {col["name"] for col in inspector.get_columns("users")}

        if "unit_preference" in existing_columns:
            print("  → unit_preference column already exists, skipping migration")
            return

        # Add unit_preference column (default: imperial)
        conn.execute(
            text("ALTER TABLE users ADD COLUMN unit_preference VARCHAR(20) DEFAULT 'imperial'")
        )
        print("  ✓ Added unit_preference column to users table")

        # Add show_both_units column (default: false)
        conn.execute(text("ALTER TABLE users ADD COLUMN show_both_units BOOLEAN DEFAULT false"))
        print("  ✓ Added show_both_units column to users table")

        # Set all existing users to imperial
        result = conn.execute(
            text(
                "UPDATE users SET unit_preference = 'imperial', show_both_units = false WHERE unit_preference IS NULL"
            )
        )
        print(f"  ✓ Set {result.rowcount} existing user(s) to imperial units")

        # Create index
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_users_unit_preference ON users(unit_preference)")
        )
        print("  ✓ Created index on users.unit_preference")

        print("\n✓ Unit preference migration completed successfully")


def downgrade():
    """Rollback not supported."""
    print("Downgrade not supported for ALTER TABLE ADD COLUMN")


if __name__ == "__main__":
    upgrade()

"""Add unit preference to user settings.

This migration adds support for per-user unit system preferences (imperial vs metric).
All data remains stored in imperial units; this setting controls display conversion only.

Default behavior:
- Existing users: imperial (maintains current behavior)
- New users: Auto-detect from timezone (US timezones → imperial, others → metric)
"""

import os
from pathlib import Path
from sqlalchemy import text, create_engine


def upgrade():
    """Add user_unit_preference column to users table."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    # Create engine
    engine = create_engine(database_url)

    with engine.begin() as conn:
        print("Adding unit preference support...")

        # Check if column already exists
        result = conn.execute(text("PRAGMA table_info(users)"))
        existing_columns = {row[1] for row in result}

        if "unit_preference" in existing_columns:
            print("  → unit_preference column already exists, skipping migration")
            return

        # Add unit_preference column (default: imperial)
        conn.execute(
            text("""
            ALTER TABLE users
            ADD COLUMN unit_preference VARCHAR(20) DEFAULT 'imperial'
        """)
        )
        print("  ✓ Added unit_preference column to users table")

        # Add show_both_units column (default: false)
        conn.execute(
            text("""
            ALTER TABLE users
            ADD COLUMN show_both_units BOOLEAN DEFAULT 0
        """)
        )
        print("  ✓ Added show_both_units column to users table")

        # Set all existing users to imperial (maintains current behavior)
        result = conn.execute(
            text("""
            UPDATE users
            SET unit_preference = 'imperial', show_both_units = 0
            WHERE unit_preference IS NULL
        """)
        )

        users_updated = result.rowcount
        print(f"  ✓ Set {users_updated} existing user(s) to imperial units")

        # Create index for faster lookups
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_users_unit_preference
            ON users(unit_preference)
        """)
        )
        print("  ✓ Created index on users.unit_preference")

        print("\n✓ Unit preference migration completed successfully")
        print("\nFeatures enabled:")
        print("  • Per-user unit system selection (imperial/metric)")
        print("  • Optional dual-unit display")
        print("  • Smart timezone-based defaults for new users")


def downgrade():
    """Rollback not supported for SQLite ALTER TABLE ADD COLUMN."""
    print("ℹ Downgrade not supported for SQLite ALTER TABLE ADD COLUMN")
    print("  The unit_preference columns will remain in the table.")


if __name__ == "__main__":
    upgrade()

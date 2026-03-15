"""Add user_id column to vehicles table for multi-user support.

This migration implements per-vehicle ownership by adding a user_id foreign key
to the vehicles table. Assigns all existing vehicles to the first user.
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
    """Add user_id column to vehicles table."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        inspector = inspect(engine)
        print("Adding user_id column to vehicles table for multi-user support...")

        existing_columns = {col["name"] for col in inspector.get_columns("vehicles")}

        if "user_id" in existing_columns:
            print("  → user_id column already exists, skipping migration")
            return

        # Get first user ID to assign existing vehicles
        first_user = conn.execute(
            text("SELECT id FROM users ORDER BY created_at LIMIT 1")
        ).fetchone()

        if not first_user:
            raise RuntimeError(
                "No users found in database - cannot assign vehicle ownership. "
                "Please create at least one user before running this migration."
            )

        first_user_id = first_user[0]
        print(f"  Found first user (id={first_user_id}) to assign existing vehicles")

        # Add user_id column (nullable initially)
        conn.execute(text("ALTER TABLE vehicles ADD COLUMN user_id INTEGER"))
        print("  ✓ Added user_id column to vehicles table")

        # Assign all existing vehicles to first user
        result = conn.execute(
            text("UPDATE vehicles SET user_id = :user_id WHERE user_id IS NULL"),
            {"user_id": first_user_id},
        )
        print(f"  ✓ Assigned {result.rowcount} existing vehicle(s) to user {first_user_id}")

        # Create index
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_vehicles_user_id ON vehicles(user_id)"))
        print("  ✓ Created index on vehicles.user_id")

        print("\n✓ Multi-user support migration completed successfully")


def downgrade():
    """Rollback not supported."""
    print("Downgrade not supported for ALTER TABLE ADD COLUMN")


if __name__ == "__main__":
    upgrade()

"""Add user_id column to vehicles table for multi-user support.

This migration implements per-vehicle ownership by adding a user_id foreign key
to the vehicles table. This enables:
- Multi-user support (each vehicle has one owner)
- Per-vehicle authorization (users can only access their own vehicles)
- Admin override (admin users can access all vehicles)

Migration strategy:
- Assigns all existing vehicles to the first user in the database
- New vehicles will be auto-assigned to current_user.id on creation
- Creates index on user_id for faster lookups
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, text


def upgrade():
    """Add user_id column to vehicles table."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    # Create engine
    engine = create_engine(database_url)

    with engine.begin() as conn:
        print("Adding user_id column to vehicles table for multi-user support...")

        # Check if column already exists
        result = conn.execute(text("PRAGMA table_info(vehicles)"))
        existing_columns = {row[1] for row in result}

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
        print(f"  • Found first user (id={first_user_id}) to assign existing vehicles")

        # Add user_id column (nullable initially)
        conn.execute(
            text("""
            ALTER TABLE vehicles
            ADD COLUMN user_id INTEGER
        """)
        )
        print("  ✓ Added user_id column to vehicles table")

        # Assign all existing vehicles to first user
        result = conn.execute(
            text("""
            UPDATE vehicles
            SET user_id = :user_id
            WHERE user_id IS NULL
        """),
            {"user_id": first_user_id},
        )

        vehicles_updated = result.rowcount
        print(
            f"  ✓ Assigned {vehicles_updated} existing vehicle(s) to user {first_user_id}"
        )

        # Create index for faster lookups
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_vehicles_user_id
            ON vehicles(user_id)
        """)
        )
        print("  ✓ Created index on vehicles.user_id")

        # Verify migration
        result = conn.execute(
            text("""
            SELECT
                COUNT(*) as total_vehicles,
                COUNT(DISTINCT user_id) as users_with_vehicles
            FROM vehicles
        """)
        )
        row = result.fetchone()

        if row:
            total_vehicles, users_with_vehicles = row
            print("\nMigration summary:")
            print(f"  Total vehicles: {total_vehicles}")
            print(f"  Users with vehicles: {users_with_vehicles}")

        print("\n✓ Multi-user support migration completed successfully")
        print("\nSecurity improvements:")
        print("  • Each vehicle now has an owner (user_id)")
        print("  • Users can only access their own vehicles")
        print("  • Admin users can access all vehicles")
        print("\nNext steps:")
        print("  1. Restart the application to apply authorization checks")
        print("  2. New vehicles will be automatically assigned to the creating user")
        print("  3. Existing vehicles are owned by the first user created")


def downgrade():
    """Rollback not supported - would require table recreation in SQLite.

    SQLite does not support DROP COLUMN directly. To rollback, you would need to:
    1. Create new table without user_id column
    2. Copy data from vehicles to new table
    3. Drop old vehicles table
    4. Rename new table to vehicles

    This is intentionally not implemented to prevent accidental data loss.
    """
    print("ℹ Downgrade not supported for SQLite ALTER TABLE ADD COLUMN")
    print("  The user_id column will remain in the table.")
    print("  To fully rollback, you would need to restore from backup.")


if __name__ == "__main__":
    upgrade()

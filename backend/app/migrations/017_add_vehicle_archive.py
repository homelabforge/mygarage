"""Add vehicle archive system.

This migration implements soft-delete functionality for vehicles with archive metadata.
Archived vehicles can be restored or permanently deleted.

Archive fields:
- archived_at: Timestamp when vehicle was archived
- archive_reason: Reason (Sold, Totaled, Gifted, Trade-in, Other)
- archive_sale_price: Sale price (optional, decimal)
- archive_sale_date: Sale/disposal date (optional)
- archive_notes: Additional notes about archive
- archived_visible: Whether to show in main vehicle list (default: true)

Archived vehicles always appear in analytics/statistics regardless of visibility.
"""

import os
from pathlib import Path
from sqlalchemy import text, create_engine


def upgrade():
    """Add archive columns to vehicles table."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    # Create engine
    engine = create_engine(database_url)

    with engine.begin() as conn:
        print("Adding vehicle archive system...")

        # Check if columns already exist
        result = conn.execute(text("PRAGMA table_info(vehicles)"))
        existing_columns = {row[1] for row in result}

        if 'archived_at' in existing_columns:
            print("  → Archive columns already exist, skipping migration")
            return

        # Add archived_at timestamp (nullable)
        conn.execute(text("""
            ALTER TABLE vehicles
            ADD COLUMN archived_at DATETIME DEFAULT NULL
        """))
        print("  ✓ Added archived_at column")

        # Add archive_reason (nullable)
        conn.execute(text("""
            ALTER TABLE vehicles
            ADD COLUMN archive_reason VARCHAR(50) DEFAULT NULL
        """))
        print("  ✓ Added archive_reason column")

        # Add archive_sale_price (nullable, decimal)
        conn.execute(text("""
            ALTER TABLE vehicles
            ADD COLUMN archive_sale_price NUMERIC(10, 2) DEFAULT NULL
        """))
        print("  ✓ Added archive_sale_price column")

        # Add archive_sale_date (nullable)
        conn.execute(text("""
            ALTER TABLE vehicles
            ADD COLUMN archive_sale_date DATE DEFAULT NULL
        """))
        print("  ✓ Added archive_sale_date column")

        # Add archive_notes (nullable, text)
        conn.execute(text("""
            ALTER TABLE vehicles
            ADD COLUMN archive_notes TEXT DEFAULT NULL
        """))
        print("  ✓ Added archive_notes column")

        # Add archived_visible (boolean, default true)
        conn.execute(text("""
            ALTER TABLE vehicles
            ADD COLUMN archived_visible BOOLEAN DEFAULT 1
        """))
        print("  ✓ Added archived_visible column")

        # Create index on archived_at for filtering
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_vehicles_archived_at
            ON vehicles(archived_at)
        """))
        print("  ✓ Created index on vehicles.archived_at")

        # Create composite index for user + archived queries
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_vehicles_user_archived
            ON vehicles(user_id, archived_at)
        """))
        print("  ✓ Created composite index on vehicles(user_id, archived_at)")

        # Count existing vehicles
        result = conn.execute(text("SELECT COUNT(*) FROM vehicles"))
        total_vehicles = result.scalar()

        print("\n✓ Vehicle archive migration completed successfully")
        print("\nMigration summary:")
        print(f"  Total vehicles: {total_vehicles}")
        print("  Archived vehicles: 0 (all existing vehicles remain active)")
        print("\nFeatures enabled:")
        print("  • Archive vehicles with metadata (reason, price, date, notes)")
        print("  • Control archived vehicle visibility in main list")
        print("  • Restore archived vehicles to active status")
        print("  • Permanent delete option for archived vehicles")
        print("  • Analytics always include archived vehicles")


def downgrade():
    """Rollback not supported for SQLite ALTER TABLE ADD COLUMN."""
    print("ℹ Downgrade not supported for SQLite ALTER TABLE ADD COLUMN")
    print("  The archive columns will remain in the table.")


if __name__ == "__main__":
    upgrade()

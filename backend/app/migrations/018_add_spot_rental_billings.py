"""Add spot_rental_billings table for tracking individual billing entries.

This migration creates a child table for spot rentals to track multiple billing
entries over time. This allows users to add monthly billing records as they occur,
rather than having a single total cost field.

Features:
- One rental can have many billing entries
- Each billing tracks: date, monthly rate, utilities (electric, water, waste), total, notes
- Cascade delete: when rental is deleted, all billings are deleted
- Indexed for efficient queries
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, text


def upgrade():
    """Create spot_rental_billings table."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    # Create engine
    engine = create_engine(database_url)

    with engine.begin() as conn:
        # Check if table already exists
        result = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='spot_rental_billings'"
            )
        )

        if result.fetchone() is not None:
            print("✓ spot_rental_billings table already exists, skipping migration")
            return

        print("Creating spot_rental_billings table...")

        # Create table
        conn.execute(
            text("""
            CREATE TABLE spot_rental_billings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spot_rental_id INTEGER NOT NULL,
                billing_date DATE NOT NULL,
                monthly_rate NUMERIC(8, 2),
                electric NUMERIC(8, 2),
                water NUMERIC(8, 2),
                waste NUMERIC(8, 2),
                total NUMERIC(10, 2),
                notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (spot_rental_id) REFERENCES spot_rentals(id) ON DELETE CASCADE
            )
        """)
        )
        print("  ✓ Created spot_rental_billings table")

        # Create index on spot_rental_id (most common query)
        conn.execute(
            text("""
            CREATE INDEX idx_spot_rental_billings_rental_id
            ON spot_rental_billings(spot_rental_id)
        """)
        )
        print("  ✓ Created index on spot_rental_id")

        # Create index on billing_date (for time-based queries)
        conn.execute(
            text("""
            CREATE INDEX idx_spot_rental_billings_date
            ON spot_rental_billings(billing_date)
        """)
        )
        print("  ✓ Created index on billing_date")

        print("\n✓ Spot rental billings migration completed successfully")
        print("\nMigration summary:")
        print("  • Created spot_rental_billings table")
        print("  • Added foreign key to spot_rentals (CASCADE delete)")
        print("  • Created indexes for optimal query performance")
        print("\nFeatures enabled:")
        print("  • Track multiple billing entries per rental")
        print("  • Record monthly rate, utilities (electric, water, waste), and total")
        print("  • Add notes to each billing entry")
        print("  • Automatic cleanup when rental is deleted")


def downgrade():
    """Rollback migration by dropping the table."""
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    engine = create_engine(database_url)

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS spot_rental_billings"))
        print("✓ Dropped spot_rental_billings table")


if __name__ == "__main__":
    upgrade()

"""Add DEF (Diesel Exhaust Fluid) tracking support.

This migration adds:
- def_records table for tracking DEF purchases and fill levels
- def_tank_capacity_gallons column on vehicles table

Schema changes:
- vehicles table: Add def_tank_capacity_gallons NUMERIC(5,2)
- def_records table: New table for DEF tracking
- Indexes: vin, date, vin+date composite, mileage
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, text


def upgrade():
    """Add DEF tracking schema."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    engine = create_engine(database_url)

    with engine.begin() as conn:
        print("Adding DEF tracking schema...")

        # =========================================================================
        # 1. Add def_tank_capacity_gallons column to vehicles table
        # =========================================================================
        result = conn.execute(text("PRAGMA table_info(vehicles)"))
        existing_columns = {row[1] for row in result.fetchall()}

        if "def_tank_capacity_gallons" in existing_columns:
            print("  → def_tank_capacity_gallons column already exists, skipping")
        else:
            conn.execute(
                text("ALTER TABLE vehicles ADD COLUMN def_tank_capacity_gallons NUMERIC(5,2)")
            )
            print("  Added def_tank_capacity_gallons column to vehicles")

        # =========================================================================
        # 2. Create def_records table
        # =========================================================================
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='def_records'")
        )
        if result.fetchone():
            print("  → def_records table already exists, skipping")
        else:
            conn.execute(
                text("""
                    CREATE TABLE def_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
                        date DATE NOT NULL,
                        mileage INTEGER CHECK (mileage IS NULL OR (mileage >= 0 AND mileage <= 9999999)),
                        gallons NUMERIC(8,3) CHECK (gallons IS NULL OR gallons >= 0),
                        cost NUMERIC(8,2) CHECK (cost IS NULL OR cost >= 0),
                        price_per_unit NUMERIC(6,3),
                        fill_level NUMERIC(3,2) CHECK (fill_level IS NULL OR (fill_level >= 0.00 AND fill_level <= 1.00)),
                        source VARCHAR(100),
                        brand VARCHAR(100),
                        notes TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            )
            print("  Created def_records table")

        # =========================================================================
        # 3. Create indexes on def_records
        # =========================================================================
        # Check existing indexes
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='def_records'")
        )
        existing_indexes = {row[0] for row in result.fetchall()}

        if "idx_def_records_vin" in existing_indexes:
            print("  → idx_def_records_vin already exists, skipping")
        else:
            conn.execute(text("CREATE INDEX idx_def_records_vin ON def_records(vin)"))
            print("  Created index idx_def_records_vin")

        if "idx_def_records_date" in existing_indexes:
            print("  → idx_def_records_date already exists, skipping")
        else:
            conn.execute(text("CREATE INDEX idx_def_records_date ON def_records(date)"))
            print("  Created index idx_def_records_date")

        if "idx_def_records_vin_date" in existing_indexes:
            print("  → idx_def_records_vin_date already exists, skipping")
        else:
            conn.execute(text("CREATE INDEX idx_def_records_vin_date ON def_records(vin, date)"))
            print("  Created index idx_def_records_vin_date")

        if "idx_def_records_mileage" in existing_indexes:
            print("  → idx_def_records_mileage already exists, skipping")
        else:
            conn.execute(text("CREATE INDEX idx_def_records_mileage ON def_records(mileage)"))
            print("  Created index idx_def_records_mileage")

        print("DEF tracking schema migration complete.")


def downgrade():
    """Downgrade not supported for this migration."""
    print("  Downgrade not supported for this migration")


if __name__ == "__main__":
    upgrade()

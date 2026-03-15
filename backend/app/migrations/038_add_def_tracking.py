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

from sqlalchemy import create_engine, inspect, text


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None):
    """Add DEF tracking schema."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        inspector = inspect(engine)
        print("Adding DEF tracking schema...")

        # =========================================================================
        # 1. Add def_tank_capacity_gallons column to vehicles table
        # =========================================================================
        existing_columns = {col["name"] for col in inspector.get_columns("vehicles")}

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
        if inspector.has_table("def_records"):
            print("  → def_records table already exists, skipping")
        else:
            is_postgres = engine.dialect.name == "postgresql"
            if is_postgres:
                conn.execute(
                    text("""
                        CREATE TABLE def_records (
                            id SERIAL PRIMARY KEY,
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
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                )
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
        # Refresh inspector after table creation
        inspector = inspect(engine)
        if inspector.has_table("def_records"):
            existing_indexes = {idx["name"] for idx in inspector.get_indexes("def_records")}

            if "idx_def_records_vin" not in existing_indexes:
                conn.execute(text("CREATE INDEX idx_def_records_vin ON def_records(vin)"))
                print("  Created index idx_def_records_vin")

            if "idx_def_records_date" not in existing_indexes:
                conn.execute(text("CREATE INDEX idx_def_records_date ON def_records(date)"))
                print("  Created index idx_def_records_date")

            if "idx_def_records_vin_date" not in existing_indexes:
                conn.execute(
                    text("CREATE INDEX idx_def_records_vin_date ON def_records(vin, date)")
                )
                print("  Created index idx_def_records_vin_date")

            if "idx_def_records_mileage" not in existing_indexes:
                conn.execute(text("CREATE INDEX idx_def_records_mileage ON def_records(mileage)"))
                print("  Created index idx_def_records_mileage")

        print("DEF tracking schema migration complete.")


def downgrade():
    """Downgrade not supported for this migration."""
    print("  Downgrade not supported for this migration")


if __name__ == "__main__":
    upgrade()

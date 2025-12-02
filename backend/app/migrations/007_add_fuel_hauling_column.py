"""Add is_hauling column to fuel_records for tracking towing/hauling trips."""

import os
from pathlib import Path
from sqlalchemy import text, create_engine


def upgrade():
    """Add is_hauling column if it does not exist."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    # Create engine
    engine = create_engine(database_url)

    with engine.begin() as conn:
        # Check if column exists via PRAGMA table_info
        result = conn.execute(text("PRAGMA table_info(fuel_records)"))
        columns = {row[1]: row for row in result}

        if 'is_hauling' not in columns:
            print("Adding is_hauling column to fuel_records table...")

            # Add column with default value
            conn.execute(text("""
                ALTER TABLE fuel_records
                ADD COLUMN is_hauling BOOLEAN DEFAULT 0 NOT NULL
            """))

            # Create indexes for better query performance
            conn.execute(text("""
                CREATE INDEX idx_fuel_hauling
                ON fuel_records(is_hauling)
            """))

            conn.execute(text("""
                CREATE INDEX idx_fuel_normal_mpg
                ON fuel_records(vin, is_full_tank, is_hauling)
            """))

            print("✓ Successfully added is_hauling to fuel_records")
        else:
            print("✓ fuel_records.is_hauling already exists")


if __name__ == "__main__":
    upgrade()

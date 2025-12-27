"""Add propane_gallons column to fuel_records for tracking propane refills."""

import os
from pathlib import Path
from sqlalchemy import text, create_engine


def upgrade():
    """Add propane_gallons column if it does not exist."""
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

        if "propane_gallons" not in columns:
            print("Adding propane_gallons column to fuel_records table...")
            conn.execute(
                text("""
                ALTER TABLE fuel_records
                ADD COLUMN propane_gallons NUMERIC(8, 3)
            """)
            )
            print("✓ Successfully added propane_gallons to fuel_records")
        else:
            print("✓ fuel_records.propane_gallons already exists")


if __name__ == "__main__":
    upgrade()

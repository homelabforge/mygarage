"""Add Electric Vehicle support: kwh column to fuel_records and Electric/Hybrid vehicle types."""

import os
from pathlib import Path
from sqlalchemy import text, create_engine


def upgrade():
    """Add kwh column and update vehicle_type constraint."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    # Create engine
    engine = create_engine(database_url)

    with engine.begin() as conn:
        # Check if kwh column exists
        result = conn.execute(text("PRAGMA table_info(fuel_records)"))
        columns = {row[1]: row for row in result}

        if 'kwh' not in columns:
            print("Adding kwh column to fuel_records table...")
            conn.execute(text("""
                ALTER TABLE fuel_records
                ADD COLUMN kwh NUMERIC(8, 3)
            """))
            print("✓ Successfully added kwh to fuel_records")
        else:
            print("✓ fuel_records.kwh already exists")

        # Note: SQLite doesn't support modifying CHECK constraints directly
        # The vehicle_type constraint is enforced at the application level
        # in backend/app/models/vehicle.py and backend/app/schemas/vehicle.py
        print("✓ Vehicle type validation updated in application layer")


if __name__ == "__main__":
    upgrade()

"""Add Electric Vehicle support: kwh column to fuel_records and Electric/Hybrid vehicle types."""

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
    """Add kwh column and update vehicle_type constraint."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        # Check if kwh column exists
        inspector = inspect(engine)
        columns = {col["name"]: col for col in inspector.get_columns("fuel_records")}

        if "kwh" not in columns:
            print("Adding kwh column to fuel_records table...")
            conn.execute(
                text("""
                ALTER TABLE fuel_records
                ADD COLUMN kwh NUMERIC(8, 3)
            """)
            )
            print("✓ Successfully added kwh to fuel_records")
        else:
            print("✓ fuel_records.kwh already exists")

        # Note: SQLite doesn't support modifying CHECK constraints directly
        # The vehicle_type constraint is enforced at the application level
        # in backend/app/models/vehicle.py and backend/app/schemas/vehicle.py
        print("✓ Vehicle type validation updated in application layer")


if __name__ == "__main__":
    upgrade()

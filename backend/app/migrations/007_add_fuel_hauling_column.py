"""Add is_hauling column to fuel_records for tracking towing/hauling trips."""

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
    """Add is_hauling column if it does not exist."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        inspector = inspect(engine)
        existing_columns = {col["name"] for col in inspector.get_columns("fuel_records")}

        if "is_hauling" not in existing_columns:
            print("Adding is_hauling column to fuel_records table...")

            conn.execute(
                text("""
                ALTER TABLE fuel_records
                ADD COLUMN is_hauling BOOLEAN DEFAULT false NOT NULL
            """)
            )

            # Create indexes for better query performance
            conn.execute(text("CREATE INDEX idx_fuel_hauling ON fuel_records(is_hauling)"))
            conn.execute(
                text(
                    "CREATE INDEX idx_fuel_normal_mpg ON fuel_records(vin, is_full_tank, is_hauling)"
                )
            )

            print("✓ Successfully added is_hauling to fuel_records")
        else:
            print("✓ fuel_records.is_hauling already exists")


if __name__ == "__main__":
    upgrade()

"""Add propane_gallons column to fuel_records for tracking propane refills."""

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
    """Add propane_gallons column if it does not exist."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        inspector = inspect(engine)
        existing_columns = {col["name"] for col in inspector.get_columns("fuel_records")}

        if "propane_gallons" not in existing_columns:
            print("Adding propane_gallons column to fuel_records table...")
            conn.execute(text("ALTER TABLE fuel_records ADD COLUMN propane_gallons NUMERIC(8, 3)"))
            print("✓ Successfully added propane_gallons to fuel_records")
        else:
            print("✓ fuel_records.propane_gallons already exists")


if __name__ == "__main__":
    upgrade()

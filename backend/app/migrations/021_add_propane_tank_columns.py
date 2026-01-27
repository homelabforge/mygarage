"""Add propane tank size tracking columns.

This migration adds tank_size_lb and tank_quantity columns to fuel_records table
to support propane tank-based entry and analytics.

Background:
- Tank sizes: 20lb, 33lb, 100lb, 420lb (common RV propane tank sizes)
- Conversion: gallons = pounds ÷ 4.24
- Both fields optional (backwards compatible)
- Validation enforced at application layer

Created: 2025-12-27
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, text


def upgrade():
    """Add tank_size_lb and tank_quantity columns to fuel_records table."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    # Create engine
    engine = create_engine(database_url)

    with engine.begin() as conn:
        # Check existing columns
        result = conn.execute(text("PRAGMA table_info(fuel_records)"))
        columns = {row[1]: row for row in result}

        # Add tank_size_lb column if it doesn't exist
        if "tank_size_lb" not in columns:
            print("Adding tank_size_lb column to fuel_records table...")
            conn.execute(
                text("""
                ALTER TABLE fuel_records
                ADD COLUMN tank_size_lb NUMERIC(6, 2)
            """)
            )
            print("✓ Successfully added tank_size_lb to fuel_records")
        else:
            print("✓ fuel_records.tank_size_lb already exists")

        # Add tank_quantity column if it doesn't exist
        if "tank_quantity" not in columns:
            print("Adding tank_quantity column to fuel_records table...")
            conn.execute(
                text("""
                ALTER TABLE fuel_records
                ADD COLUMN tank_quantity INTEGER
            """)
            )
            print("✓ Successfully added tank_quantity to fuel_records")
        else:
            print("✓ fuel_records.tank_quantity already exists")

        # Note: Validation enforced at application level
        # - Both tank_size_lb AND tank_quantity must be set together (or both null)
        # - Enforced in backend/app/schemas/fuel.py
        print("✓ Tank field validation updated in application layer")


if __name__ == "__main__":
    upgrade()

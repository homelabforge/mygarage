"""
Migration: Add VIN decoded fields to vehicles table

Adds fields from NHTSA VIN decode:
- trim, body_class, drive_type, doors, gvwr_class, displacement_l,
- cylinders, fuel_type, transmission_type, transmission_speeds
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
    """Add VIN decoded fields to vehicles table."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        inspector = inspect(engine)
        existing_columns = {col["name"] for col in inspector.get_columns("vehicles")}

        columns_to_add = [
            ("trim", "VARCHAR(50)"),
            ("body_class", "VARCHAR(50)"),
            ("drive_type", "VARCHAR(30)"),
            ("doors", "INTEGER"),
            ("gvwr_class", "VARCHAR(50)"),
            ("displacement_l", "VARCHAR(20)"),
            ("cylinders", "INTEGER"),
            ("fuel_type", "VARCHAR(50)"),
            ("transmission_type", "VARCHAR(50)"),
            ("transmission_speeds", "VARCHAR(20)"),
        ]

        added_count = 0
        for col_name, col_type in columns_to_add:
            if col_name not in existing_columns:
                try:
                    conn.execute(text(f"ALTER TABLE vehicles ADD COLUMN {col_name} {col_type}"))
                    print(f"Adding column: {col_name}")
                    added_count += 1
                except Exception as e:
                    print(f"Error adding {col_name}: {e}")
            else:
                print(f"Column {col_name} already exists, skipping")

    print(f"\nMigration complete! Added {added_count} new columns.")


if __name__ == "__main__":
    upgrade()

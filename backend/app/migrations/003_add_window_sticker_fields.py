"""Add window sticker fields to vehicles table for sticker upload and OCR data."""

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
    """Add window sticker columns if they do not exist."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        inspector = inspect(engine)
        existing_columns = {col["name"] for col in inspector.get_columns("vehicles")}

        is_postgres = engine.dialect.name == "postgresql"
        ts_type = "TIMESTAMP" if is_postgres else "DATETIME"

        columns_to_add = [
            ("window_sticker_file_path", "VARCHAR(255)"),
            ("window_sticker_uploaded_at", ts_type),
            ("msrp_base", "NUMERIC(10, 2)"),
            ("msrp_options", "NUMERIC(10, 2)"),
            ("msrp_total", "NUMERIC(10, 2)"),
            ("fuel_economy_city", "INTEGER"),
            ("fuel_economy_highway", "INTEGER"),
            ("fuel_economy_combined", "INTEGER"),
            ("standard_equipment", "JSON" if is_postgres else "JSON"),
            ("optional_equipment", "JSON" if is_postgres else "JSON"),
            ("assembly_location", "VARCHAR(100)"),
        ]

        for column_name, column_type in columns_to_add:
            if column_name in existing_columns:
                print(f"✓ vehicles.{column_name} already exists")
            else:
                conn.execute(text(f"ALTER TABLE vehicles ADD COLUMN {column_name} {column_type}"))
                print(f"✓ Added {column_name} column to vehicles")


def downgrade():
    """
    SQLite cannot drop columns easily without recreating the table.
    For now, this downgrade is a no-op to avoid data loss.
    """
    print("downgrade skipped (window sticker columns will remain)")


if __name__ == "__main__":
    upgrade()

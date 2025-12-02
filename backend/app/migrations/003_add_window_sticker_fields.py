"""Add window sticker fields to vehicles table for sticker upload and OCR data."""

import os
from pathlib import Path
from sqlalchemy import text, create_engine


def upgrade():
    """Add window sticker columns if they do not exist."""
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    engine = create_engine(database_url)

    with engine.begin() as conn:
        result = conn.execute(text("PRAGMA table_info(vehicles)"))
        existing_columns = {row[1] for row in result}

        columns_to_add = [
            ("window_sticker_file_path", "VARCHAR(255)"),
            ("window_sticker_uploaded_at", "DATETIME"),
            ("msrp_base", "NUMERIC(10, 2)"),
            ("msrp_options", "NUMERIC(10, 2)"),
            ("msrp_total", "NUMERIC(10, 2)"),
            ("fuel_economy_city", "INTEGER"),
            ("fuel_economy_highway", "INTEGER"),
            ("fuel_economy_combined", "INTEGER"),
            ("standard_equipment", "JSON"),
            ("optional_equipment", "JSON"),
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
    print("ℹ downgrade skipped (window sticker columns will remain)")


if __name__ == "__main__":
    upgrade()

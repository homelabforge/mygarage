"""Add enhanced window sticker fields to vehicles table for full data extraction."""

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
    """Add enhanced window sticker columns if they do not exist."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        inspector = inspect(engine)
        existing_columns = {col["name"] for col in inspector.get_columns("vehicles")}

        columns_to_add = [
            ("destination_charge", "NUMERIC(10, 2)"),
            ("window_sticker_options_detail", "JSON"),
            ("window_sticker_packages", "JSON"),
            ("exterior_color", "VARCHAR(100)"),
            ("interior_color", "VARCHAR(100)"),
            ("sticker_engine_description", "VARCHAR(150)"),
            ("sticker_transmission_description", "VARCHAR(150)"),
            ("sticker_drivetrain", "VARCHAR(50)"),
            ("wheel_specs", "VARCHAR(100)"),
            ("tire_specs", "VARCHAR(100)"),
            ("warranty_powertrain", "VARCHAR(100)"),
            ("warranty_basic", "VARCHAR(100)"),
            ("environmental_rating_ghg", "VARCHAR(10)"),
            ("environmental_rating_smog", "VARCHAR(10)"),
            ("window_sticker_parser_used", "VARCHAR(50)"),
            ("window_sticker_confidence_score", "NUMERIC(5, 2)"),
            ("window_sticker_extracted_vin", "VARCHAR(17)"),
        ]

        for column_name, column_type in columns_to_add:
            if column_name in existing_columns:
                print(f"✓ vehicles.{column_name} already exists")
            else:
                conn.execute(text(f"ALTER TABLE vehicles ADD COLUMN {column_name} {column_type}"))
                print(f"✓ Added {column_name} column to vehicles")


def downgrade():
    """Downgrade is a no-op to avoid data loss."""
    print("downgrade skipped (enhanced window sticker columns will remain)")


if __name__ == "__main__":
    upgrade()

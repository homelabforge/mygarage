"""Add enhanced window sticker fields to vehicles table for full data extraction."""

import os
from pathlib import Path
from sqlalchemy import text, create_engine


def upgrade():
    """Add enhanced window sticker columns if they do not exist."""
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    engine = create_engine(database_url)

    with engine.begin() as conn:
        result = conn.execute(text("PRAGMA table_info(vehicles)"))
        existing_columns = {row[1] for row in result}

        columns_to_add = [
            # Destination charge (separate from options)
            ("destination_charge", "NUMERIC(10, 2)"),
            # Individual options with pricing (JSON: {"option_name": price, ...})
            ("window_sticker_options_detail", "JSON"),
            # Package contents (JSON: {"Package Name": ["item1", "item2"], ...})
            ("window_sticker_packages", "JSON"),
            # Colors as dedicated fields
            ("exterior_color", "VARCHAR(100)"),
            ("interior_color", "VARCHAR(100)"),
            # Engine/transmission from sticker (may differ from VIN decode)
            ("sticker_engine_description", "VARCHAR(150)"),
            ("sticker_transmission_description", "VARCHAR(150)"),
            ("sticker_drivetrain", "VARCHAR(50)"),
            # Wheel and tire specs
            ("wheel_specs", "VARCHAR(100)"),
            ("tire_specs", "VARCHAR(100)"),
            # Warranty information
            ("warranty_powertrain", "VARCHAR(100)"),
            ("warranty_basic", "VARCHAR(100)"),
            # Environmental ratings (CARB/EPA)
            ("environmental_rating_ghg", "VARCHAR(10)"),
            ("environmental_rating_smog", "VARCHAR(10)"),
            # Parser metadata
            ("window_sticker_parser_used", "VARCHAR(50)"),
            ("window_sticker_confidence_score", "NUMERIC(5, 2)"),
            ("window_sticker_extracted_vin", "VARCHAR(17)"),
        ]

        for column_name, column_type in columns_to_add:
            if column_name in existing_columns:
                print(f"✓ vehicles.{column_name} already exists")
            else:
                conn.execute(
                    text(f"ALTER TABLE vehicles ADD COLUMN {column_name} {column_type}")
                )
                print(f"✓ Added {column_name} column to vehicles")


def downgrade():
    """
    SQLite cannot drop columns easily without recreating the table.
    For now, this downgrade is a no-op to avoid data loss.
    """
    print("ℹ downgrade skipped (enhanced window sticker columns will remain)")


if __name__ == "__main__":
    upgrade()

"""Add thumbnail_path column to vehicle_photos for thumbnail support."""

import os
from pathlib import Path

from sqlalchemy import create_engine, text


def upgrade():
    """Add thumbnail_path column if it does not exist."""
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    engine = create_engine(database_url)

    with engine.begin() as conn:
        result = conn.execute(text("PRAGMA table_info(vehicle_photos)"))
        existing_columns = {row[1] for row in result}

        if "thumbnail_path" in existing_columns:
            print("✓ vehicle_photos.thumbnail_path already exists")
            return

        conn.execute(text("ALTER TABLE vehicle_photos ADD COLUMN thumbnail_path VARCHAR(255)"))
        print("✓ Added thumbnail_path column to vehicle_photos")


def downgrade():
    """
    SQLite cannot drop columns easily without recreating the table.
    For now, this downgrade is a no-op to avoid data loss.
    """
    print("ℹ downgrade skipped (thumbnail_path column will remain)")


if __name__ == "__main__":
    upgrade()

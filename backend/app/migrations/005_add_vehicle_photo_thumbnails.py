"""Add thumbnail_path column to vehicle_photos for thumbnail support."""

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
    """Add thumbnail_path column if it does not exist."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        inspector = inspect(engine)
        existing_columns = {col["name"] for col in inspector.get_columns("vehicle_photos")}

        if "thumbnail_path" in existing_columns:
            print("✓ vehicle_photos.thumbnail_path already exists")
            return

        conn.execute(text("ALTER TABLE vehicle_photos ADD COLUMN thumbnail_path VARCHAR(255)"))
        print("✓ Added thumbnail_path column to vehicle_photos")


def downgrade():
    """Downgrade is a no-op to avoid data loss."""
    print("downgrade skipped (thumbnail_path column will remain)")


if __name__ == "__main__":
    upgrade()

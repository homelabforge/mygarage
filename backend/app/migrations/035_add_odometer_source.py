"""Add source column to odometer_records table.

This migration adds a 'source' column to track where odometer readings came from:
- 'manual': User entered manually (default)
- 'livelink': Auto-recorded from LiveLink telemetry
- 'service': Recorded during service visit
- 'fuel': Recorded during fuel fill-up

This allows the UI to distinguish automatic LiveLink entries from manual ones.
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
    """Add source column to odometer_records."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        inspector = inspect(engine)

        # Check if odometer_records table exists
        if not inspector.has_table("odometer_records"):
            print("  odometer_records table does not exist, skipping")
            return

        # Check if source column already exists
        existing_columns = {col["name"] for col in inspector.get_columns("odometer_records")}

        if "source" in existing_columns:
            print("  source column already exists, skipping")
        else:
            # Add source column with default 'manual'
            conn.execute(
                text("""
                    ALTER TABLE odometer_records
                    ADD COLUMN source VARCHAR(20) DEFAULT 'manual'
                """)
            )
            print("  Added source column to odometer_records")

        # Create index on source column if it doesn't exist
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("odometer_records")}
        if "idx_odometer_source" not in existing_indexes:
            conn.execute(text("CREATE INDEX idx_odometer_source ON odometer_records(source)"))
            print("  Created idx_odometer_source index")

    print("  Migration 035 complete - odometer source column added")


if __name__ == "__main__":
    upgrade()

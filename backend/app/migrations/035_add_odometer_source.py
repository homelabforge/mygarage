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

from sqlalchemy import create_engine, text


def upgrade():
    """Add source column to odometer_records."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    engine = create_engine(database_url)

    with engine.begin() as conn:
        # Check if odometer_records table exists
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='odometer_records'")
        )
        if not result.fetchone():
            print("  odometer_records table does not exist, skipping")
            return

        # Check if source column already exists
        result = conn.execute(text("PRAGMA table_info(odometer_records)"))
        existing_columns = {row[1] for row in result.fetchall()}

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
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_odometer_source'")
        )
        if not result.fetchone():
            conn.execute(text("CREATE INDEX idx_odometer_source ON odometer_records(source)"))
            print("  Created idx_odometer_source index")

    print("  Migration 035 complete - odometer source column added")


if __name__ == "__main__":
    upgrade()

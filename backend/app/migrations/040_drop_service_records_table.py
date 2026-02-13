"""Drop the legacy service_records table.

The ServiceRecord model was fully replaced by ServiceVisit + ServiceLineItem
in migration 028. All data was migrated in that migration. CSV/JSON import/export
and attachments have been updated to use ServiceVisit. This migration drops the
now-unused table.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, text


def upgrade():
    """Drop the service_records table if it exists."""
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    engine = create_engine(database_url)

    with engine.begin() as conn:
        # Check if the table exists before dropping
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='service_records'")
        )
        if not result.fetchone():
            print("  service_records table does not exist, skipping")
            return

        # Also migrate any remaining attachments with record_type='service'
        # to 'service_visit' before dropping
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='attachments'")
        )
        if result.fetchone():
            updated = conn.execute(
                text(
                    "UPDATE attachments SET record_type = 'service_visit' WHERE record_type = 'service'"
                )
            )
            if updated.rowcount > 0:
                print(
                    f"  Migrated {updated.rowcount} attachment(s) from record_type='service' to 'service_visit'"
                )

        conn.execute(text("DROP TABLE service_records"))
        print("  Dropped service_records table")

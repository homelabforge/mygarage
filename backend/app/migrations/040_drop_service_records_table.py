"""Drop the legacy service_records table.

The ServiceRecord model was fully replaced by ServiceVisit + ServiceLineItem
in migration 028. All data was migrated in that migration. CSV/JSON import/export
and attachments have been updated to use ServiceVisit. This migration drops the
now-unused table.
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
    """Drop the service_records table if it exists."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        # Check if the table exists before dropping
        if not inspect(engine).has_table("service_records"):
            print("  service_records table does not exist, skipping")
            return

        # Also migrate any remaining attachments with record_type='service'
        # to 'service_visit' before dropping
        if inspect(engine).has_table("attachments"):
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

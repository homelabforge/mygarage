"""Add entry_type and origin_fuel_record_id to def_records.

This migration adds:
- entry_type column to distinguish purchase vs auto-synced DEF records
- origin_fuel_record_id FK linking auto-synced records back to their fuel record
- Indexes for both new columns

Schema changes:
- def_records: Add entry_type VARCHAR(20) DEFAULT 'purchase'
- def_records: Add origin_fuel_record_id INTEGER REFERENCES fuel_records(id)
- Indexes: idx_def_entry_type, idx_def_origin_fuel_record_id
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
    """Add entry_type and origin_fuel_record_id to def_records."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        print("Adding DEF entry_type and fuel record link...")

        # =========================================================================
        # 1. Add entry_type column to def_records
        # =========================================================================
        inspector = inspect(engine)
        existing_columns = {col["name"] for col in inspector.get_columns("def_records")}

        if "entry_type" in existing_columns:
            print("  → entry_type column already exists, skipping")
        else:
            conn.execute(
                text(
                    "ALTER TABLE def_records ADD COLUMN entry_type VARCHAR(20) "
                    "DEFAULT 'purchase' "
                    "CHECK (entry_type IN ('purchase', 'auto_fuel_sync'))"
                )
            )
            print("  Added entry_type column to def_records")

        # =========================================================================
        # 2. Add origin_fuel_record_id column to def_records
        # =========================================================================
        if "origin_fuel_record_id" in existing_columns:
            print("  → origin_fuel_record_id column already exists, skipping")
        else:
            conn.execute(
                text(
                    "ALTER TABLE def_records ADD COLUMN origin_fuel_record_id INTEGER "
                    "REFERENCES fuel_records(id) ON DELETE SET NULL"
                )
            )
            print("  Added origin_fuel_record_id column to def_records")

        # =========================================================================
        # 3. Create indexes
        # =========================================================================
        existing_indexes = {idx["name"] for idx in inspect(engine).get_indexes("def_records")}

        if "idx_def_entry_type" in existing_indexes:
            print("  → idx_def_entry_type already exists, skipping")
        else:
            conn.execute(text("CREATE INDEX idx_def_entry_type ON def_records(entry_type)"))
            print("  Created index idx_def_entry_type")

        if "idx_def_origin_fuel_record_id" in existing_indexes:
            print("  → idx_def_origin_fuel_record_id already exists, skipping")
        else:
            conn.execute(
                text(
                    "CREATE INDEX idx_def_origin_fuel_record_id "
                    "ON def_records(origin_fuel_record_id)"
                )
            )
            print("  Created index idx_def_origin_fuel_record_id")

        print("DEF entry_type and fuel record link migration complete.")


def downgrade():
    """Downgrade not supported for this migration."""
    print("  Downgrade not supported for this migration")


if __name__ == "__main__":
    upgrade()

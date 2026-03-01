"""Add notification tracking columns for dedup.

Adds last_notified_at and last_notified_status to maintenance_schedule_items,
and last_notified_at to insurance_policies and warranty_records.

These columns prevent duplicate notifications by tracking when and what
status was last notified. A 24-hour cooldown per status is enforced in
the notification scheduler jobs.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


def upgrade() -> None:
    """Add notification tracking columns."""
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    engine = create_engine(database_url)

    with engine.begin() as conn:
        inspector = inspect(engine)

        # maintenance_schedule_items: last_notified_at, last_notified_status
        columns = [col["name"] for col in inspector.get_columns("maintenance_schedule_items")]

        if "last_notified_at" not in columns:
            conn.execute(
                text("ALTER TABLE maintenance_schedule_items ADD COLUMN last_notified_at DATETIME")
            )
            print("  Added column: maintenance_schedule_items.last_notified_at")

        if "last_notified_status" not in columns:
            conn.execute(
                text(
                    "ALTER TABLE maintenance_schedule_items ADD COLUMN last_notified_status VARCHAR(20)"
                )
            )
            print("  Added column: maintenance_schedule_items.last_notified_status")

        # insurance_policies: last_notified_at
        columns = [col["name"] for col in inspector.get_columns("insurance_policies")]

        if "last_notified_at" not in columns:
            conn.execute(
                text("ALTER TABLE insurance_policies ADD COLUMN last_notified_at DATETIME")
            )
            print("  Added column: insurance_policies.last_notified_at")

        # warranty_records: last_notified_at
        columns = [col["name"] for col in inspector.get_columns("warranty_records")]

        if "last_notified_at" not in columns:
            conn.execute(text("ALTER TABLE warranty_records ADD COLUMN last_notified_at DATETIME"))
            print("  Added column: warranty_records.last_notified_at")

    print("  Migration 046 complete: notification tracking columns added")


def downgrade() -> None:
    """Downgrade not supported — columns retained for safety."""
    print("  Downgrade not supported — columns retained for safety")


if __name__ == "__main__":
    upgrade()

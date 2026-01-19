"""Cleanup reminders that were converted to maintenance_schedule_items in migration 028.

This migration removes reminders that were converted to schedule items but not deleted
due to the delete logic being added after the initial migration run.
"""

import os
from pathlib import Path
from sqlalchemy import text, create_engine


def upgrade():
    """Delete non-completed reminders that have corresponding schedule items."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    # Create engine
    engine = create_engine(database_url)

    with engine.begin() as conn:
        # Check if both tables exist
        result = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='reminders'"
            )
        )
        if not result.fetchone():
            print("  reminders table does not exist, skipping")
            return

        result = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='maintenance_schedule_items'"
            )
        )
        if not result.fetchone():
            print("  maintenance_schedule_items table does not exist, skipping")
            return

        # Count reminders to be deleted
        result = conn.execute(
            text("SELECT COUNT(*) FROM reminders WHERE is_completed = 0")
        )
        reminder_count = result.scalar() or 0

        if reminder_count == 0:
            print("  No non-completed reminders to clean up")
            return

        # Check if schedule items exist (meaning migration 028 ran)
        result = conn.execute(text("SELECT COUNT(*) FROM maintenance_schedule_items"))
        schedule_count = result.scalar() or 0

        if schedule_count == 0:
            print(
                "  No schedule items exist - reminders not yet converted, skipping cleanup"
            )
            return

        print(
            f"  Found {reminder_count} non-completed reminders and {schedule_count} schedule items"
        )
        print(
            "  Deleting non-completed reminders that were converted to schedule items..."
        )

        # Delete non-completed reminders (these were converted in migration 028)
        conn.execute(text("DELETE FROM reminders WHERE is_completed = 0"))

        print(f"  Deleted {reminder_count} reminder(s)")


if __name__ == "__main__":
    upgrade()

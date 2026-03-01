"""Archive completed reminders as historical service visits, then drop reminders table.

Migration 028 converted active (is_completed=0) reminders to maintenance_schedule_items.
Migration 029 deleted the converted non-completed reminders.
This migration archives any remaining completed reminders as historical service visits
(preserving the data), then drops the reminders table entirely.

Dedup key: notes field contains '[Archived Reminder #<id>]' — deterministic per reminder ID.
"""

import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text


def upgrade() -> None:
    """Archive completed reminders as service visits, then drop reminders table."""
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    engine = create_engine(database_url)

    with engine.begin() as conn:
        # Check if reminders table exists
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='reminders'")
        )
        if not result.fetchone():
            print("  reminders table does not exist — nothing to do")
            return

        # Fetch completed reminders that haven't been archived yet
        completed = conn.execute(
            text(
                "SELECT id, vin, description, completed_at, created_at FROM reminders WHERE is_completed = 1"
            )
        ).fetchall()

        archived_count = 0
        for row in completed:
            reminder_id = row[0]
            vin = row[1]
            description = row[2]
            completed_at = row[3]
            created_at = row[4]

            # Deterministic dedup marker
            marker = f"[Archived Reminder #{reminder_id}]"

            # Check if already archived (idempotency)
            existing = conn.execute(
                text("SELECT id FROM service_visits WHERE notes LIKE :pattern"),
                {"pattern": f"{marker}%"},
            ).fetchone()

            if existing:
                continue

            # Use completed_at as the visit date, fall back to created_at, then today
            visit_date = completed_at or created_at or datetime.now().isoformat()
            # Extract just the date portion if it's a full datetime
            if isinstance(visit_date, str) and "T" in visit_date:
                visit_date = visit_date.split("T")[0]
            elif isinstance(visit_date, str) and " " in visit_date:
                visit_date = visit_date.split(" ")[0]

            notes = f"{marker} {description}"

            # Insert service visit
            conn.execute(
                text(
                    """
                    INSERT INTO service_visits (vin, date, service_category, notes, total_cost)
                    VALUES (:vin, :date, 'Maintenance', :notes, 0)
                    """
                ),
                {"vin": vin, "date": visit_date, "notes": notes},
            )

            # Get the visit ID we just created
            visit_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()

            # Insert a service line item for the archived reminder
            conn.execute(
                text(
                    """
                    INSERT INTO service_line_items (visit_id, description, cost)
                    VALUES (:visit_id, :description, 0)
                    """
                ),
                {"visit_id": visit_id, "description": description},
            )

            archived_count += 1

        if archived_count > 0:
            print(f"  Archived {archived_count} completed reminders as service visits")

        # Now drop the reminders table
        conn.execute(text("DROP TABLE IF EXISTS reminders"))
        print("  Dropped reminders table")


def downgrade() -> None:
    """Downgrade not supported — archived data is preserved in service_visits."""
    print("  Downgrade not supported — reminder data preserved in service_visits")


if __name__ == "__main__":
    upgrade()

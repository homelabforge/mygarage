"""Migrate service attachments from old service_records to new service_visits.

This migration:
1. Updates the attachment CHECK constraint to include 'service_visit'
2. Maps existing 'service' attachments to 'service_visit' using date+VIN matching
3. Updates record_type and record_id accordingly
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, text


def upgrade():
    """Migrate service attachments to service_visit records."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    # Create engine
    engine = create_engine(database_url)

    with engine.begin() as conn:
        # Check if attachments table exists
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='attachments'")
        )
        if not result.fetchone():
            print("  attachments table does not exist, skipping")
            return

        # Check if service_visits table exists
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='service_visits'")
        )
        if not result.fetchone():
            print("  service_visits table does not exist, skipping")
            return

        # Check if service_records table exists
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='service_records'")
        )
        if not result.fetchone():
            print("  service_records table does not exist, skipping")
            return

        # Count attachments to migrate
        result = conn.execute(
            text("SELECT COUNT(*) FROM attachments WHERE record_type = 'service'")
        )
        attachment_count = result.scalar() or 0

        if attachment_count == 0:
            print("  No service attachments to migrate")
            return

        print(f"  Found {attachment_count} service attachment(s) to migrate")

        # Step 1: Create new attachments table with updated constraint
        print("  Updating attachments table constraint...")
        conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS attachments_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_type VARCHAR(30) NOT NULL,
                record_id INTEGER NOT NULL,
                file_path VARCHAR(255) NOT NULL,
                file_type VARCHAR(10),
                file_size INTEGER,
                uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                CHECK (record_type IN ('service', 'service_visit', 'fuel', 'upgrade', 'collision', 'tax', 'note'))
            )
        """
            )
        )

        # Step 2: Build mapping from old service_records to new service_visits
        result = conn.execute(
            text(
                """
            SELECT sr.id as old_id, sv.id as new_id
            FROM service_records sr
            INNER JOIN service_visits sv ON sr.vin = sv.vin AND sr.date = sv.date
        """
            )
        )
        mapping = {row[0]: row[1] for row in result.fetchall()}
        print(f"  Built mapping for {len(mapping)} service record(s)")

        # Step 3: Copy all attachments, converting 'service' to 'service_visit' with new IDs
        result = conn.execute(
            text(
                """
            SELECT id, record_type, record_id, file_path, file_type, file_size, uploaded_at
            FROM attachments
        """
            )
        )
        rows = result.fetchall()

        migrated = 0
        for row in rows:
            (
                att_id,
                record_type,
                record_id,
                file_path,
                file_type,
                file_size,
                uploaded_at,
            ) = row

            if record_type == "service" and record_id in mapping:
                # Migrate to service_visit
                new_record_type = "service_visit"
                new_record_id = mapping[record_id]
                migrated += 1
            else:
                # Keep as-is
                new_record_type = record_type
                new_record_id = record_id

            conn.execute(
                text(
                    """
                INSERT INTO attachments_new
                (id, record_type, record_id, file_path, file_type, file_size, uploaded_at)
                VALUES (:id, :record_type, :record_id, :file_path, :file_type, :file_size, :uploaded_at)
            """
                ),
                {
                    "id": att_id,
                    "record_type": new_record_type,
                    "record_id": new_record_id,
                    "file_path": file_path,
                    "file_type": file_type,
                    "file_size": file_size,
                    "uploaded_at": uploaded_at,
                },
            )

        # Step 4: Drop old table and rename new one
        conn.execute(text("DROP TABLE attachments"))
        conn.execute(text("ALTER TABLE attachments_new RENAME TO attachments"))

        # Step 5: Recreate index
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_attachments_record ON attachments(record_type, record_id)"
            )
        )

        print(f"  Migrated {migrated} attachment(s) to service_visit")


if __name__ == "__main__":
    upgrade()

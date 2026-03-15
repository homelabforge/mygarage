"""Migrate service attachments from old service_records to new service_visits.

This migration:
1. Updates the attachment CHECK constraint to include 'service_visit'
2. Maps existing 'service' attachments to 'service_visit' using date+VIN matching
3. Updates record_type and record_id accordingly

Constraint update and row remapping are independent steps — if the constraint
is already updated, the row remap still runs to catch partial prior executions.
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
    """Migrate service attachments to service_visit records."""
    if engine is None:
        engine = _get_fallback_engine()

    is_postgres = engine.dialect.name == "postgresql"
    pk_type = "SERIAL PRIMARY KEY" if is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts_type = "TIMESTAMP" if is_postgres else "DATETIME"

    with engine.begin() as conn:
        inspector = inspect(engine)

        # Check if attachments table exists
        if not inspector.has_table("attachments"):
            print("  attachments table does not exist, skipping")
            return

        # Check if service_visits table exists
        if not inspector.has_table("service_visits"):
            print("  service_visits table does not exist, skipping")
            return

        # Check if service_records table exists (needed for mapping)
        has_service_records = inspector.has_table("service_records")

        if is_postgres:
            _upgrade_postgres(conn, has_service_records)
        else:
            _upgrade_sqlite(conn, pk_type, ts_type, has_service_records)


def _upgrade_postgres(conn, has_service_records: bool) -> None:
    """PostgreSQL: update constraint in-place and remap rows."""
    # Step 1: Update CHECK constraint if needed
    result = conn.execute(
        text("""
            SELECT conname, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'attachments'::regclass
              AND contype = 'c'
              AND pg_get_constraintdef(oid) LIKE '%record_type%'
        """)
    )
    constraint_row = result.fetchone()

    if constraint_row:
        conname = constraint_row[0]
        condef = constraint_row[1]
        if "service_visit" not in condef:
            # Drop old constraint and add updated one
            conn.execute(text(f"ALTER TABLE attachments DROP CONSTRAINT {conname}"))
            conn.execute(
                text("""
                    ALTER TABLE attachments ADD CONSTRAINT attachments_record_type_check
                    CHECK (record_type IN ('service', 'service_visit', 'fuel', 'upgrade', 'collision', 'tax', 'note'))
                """)
            )
            print("  Updated CHECK constraint to include 'service_visit'")
        else:
            print("  CHECK constraint already includes 'service_visit'")
    else:
        # No CHECK constraint found — add one
        conn.execute(
            text("""
                ALTER TABLE attachments ADD CONSTRAINT attachments_record_type_check
                CHECK (record_type IN ('service', 'service_visit', 'fuel', 'upgrade', 'collision', 'tax', 'note'))
            """)
        )
        print("  Added CHECK constraint for record_type")

    # Step 2: Remap rows (independent of constraint step)
    _remap_service_rows(conn, has_service_records)


def _upgrade_sqlite(conn, pk_type: str, ts_type: str, has_service_records: bool) -> None:
    """SQLite: rebuild table to update CHECK constraint, then remap rows."""
    # Count attachments to migrate
    result = conn.execute(text("SELECT COUNT(*) FROM attachments WHERE record_type = 'service'"))
    attachment_count = result.scalar() or 0

    if attachment_count == 0:
        print("  No service attachments to migrate")
        return

    print(f"  Found {attachment_count} service attachment(s) to migrate")

    # Build mapping before table rebuild
    mapping = _build_mapping(conn, has_service_records)

    # Create new table with updated constraint
    print("  Updating attachments table constraint...")
    conn.execute(text("DROP TABLE IF EXISTS attachments_new"))
    conn.execute(
        text(
            f"""
        CREATE TABLE attachments_new (
            id {pk_type},
            record_type VARCHAR(30) NOT NULL,
            record_id INTEGER NOT NULL,
            file_path VARCHAR(255) NOT NULL,
            file_type VARCHAR(10),
            file_size INTEGER,
            uploaded_at {ts_type} DEFAULT CURRENT_TIMESTAMP,
            CHECK (record_type IN ('service', 'service_visit', 'fuel', 'upgrade', 'collision', 'tax', 'note'))
        )
    """
        )
    )

    # Copy all attachments, converting 'service' to 'service_visit' with new IDs
    result = conn.execute(
        text(
            "SELECT id, record_type, record_id, file_path, file_type, file_size, uploaded_at FROM attachments"
        )
    )
    rows = result.fetchall()

    migrated = 0
    for row in rows:
        att_id, record_type, record_id, file_path, file_type, file_size, uploaded_at = row

        if record_type == "service" and record_id in mapping:
            new_record_type = "service_visit"
            new_record_id = mapping[record_id]
            migrated += 1
        else:
            new_record_type = record_type
            new_record_id = record_id

        conn.execute(
            text("""
                INSERT INTO attachments_new
                (id, record_type, record_id, file_path, file_type, file_size, uploaded_at)
                VALUES (:id, :record_type, :record_id, :file_path, :file_type, :file_size, :uploaded_at)
            """),
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

    # Replace table
    conn.execute(text("DROP TABLE attachments"))
    conn.execute(text("ALTER TABLE attachments_new RENAME TO attachments"))

    # Recreate index
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_attachments_record ON attachments(record_type, record_id)"
        )
    )

    print(f"  Migrated {migrated} attachment(s) to service_visit")


def _build_mapping(conn, has_service_records: bool) -> dict:
    """Build old service_records ID → new service_visits ID mapping."""
    if not has_service_records:
        return {}

    result = conn.execute(
        text("""
            SELECT sr.id as old_id, sv.id as new_id
            FROM service_records sr
            INNER JOIN service_visits sv ON sr.vin = sv.vin AND sr.date = sv.date
        """)
    )
    mapping = {row[0]: row[1] for row in result.fetchall()}
    print(f"  Built mapping for {len(mapping)} service record(s)")
    return mapping


def _remap_service_rows(conn, has_service_records: bool) -> None:
    """Remap record_type='service' attachment rows to 'service_visit' in-place."""
    # Count rows to remap
    result = conn.execute(text("SELECT COUNT(*) FROM attachments WHERE record_type = 'service'"))
    service_count = result.scalar() or 0

    if service_count == 0:
        print("  No service attachment rows to remap")
        return

    print(f"  Found {service_count} service attachment(s) to remap")

    mapping = _build_mapping(conn, has_service_records)

    if not mapping:
        print("  No service_records → service_visits mapping available, skipping row remap")
        return

    # Update each mapped row in-place
    migrated = 0
    for old_id, new_id in mapping.items():
        result = conn.execute(
            text("""
                UPDATE attachments
                SET record_type = 'service_visit', record_id = :new_id
                WHERE record_type = 'service' AND record_id = :old_id
            """),
            {"old_id": old_id, "new_id": new_id},
        )
        migrated += result.rowcount

    # Ensure index exists
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_attachments_record ON attachments(record_type, record_id)"
        )
    )

    print(f"  Remapped {migrated} attachment(s) to service_visit")


if __name__ == "__main__":
    upgrade()

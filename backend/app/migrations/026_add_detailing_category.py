"""Migration 026: Add Detailing category and repurpose TSB column.

This migration:
1. Drops the unused TSB column from service_records table
2. Adds service_category column with CHECK constraint including 'Detailing'
3. Updates existing service_category constraint to include 'Detailing'

Since the TSB column is unused and the TSB feature has been removed,
we drop it and ensure the service_category column has the correct constraint.
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
    """Run migration 026."""
    if engine is None:
        engine = _get_fallback_engine()

    dialect = engine.dialect.name

    with engine.begin() as conn:
        inspector = inspect(engine)

        if not inspector.has_table("service_records"):
            print("  service_records table does not exist, skipping")
            return

        existing_columns = {col["name"] for col in inspector.get_columns("service_records")}
        has_tsb_column = "tsb_id" in existing_columns

        print("\n=== Migration 026: Add Detailing Category ===\n")

        if has_tsb_column:
            print("Found unused TSB column - will be dropped")

        if dialect == "postgresql":
            # PostgreSQL: can alter constraints and drop columns directly

            # Drop TSB column if it exists
            if has_tsb_column:
                conn.execute(text("ALTER TABLE service_records DROP COLUMN tsb_id"))
                print("✓ TSB column dropped")

            # Update CHECK constraint to include 'Detailing'
            # First check if 'Detailing' is already there
            result = conn.execute(
                text("""
                    SELECT conname, pg_get_constraintdef(oid)
                    FROM pg_constraint
                    WHERE conrelid = 'service_records'::regclass
                    AND contype = 'c'
                    AND conname = 'check_service_category'
                """)
            )
            row = result.fetchone()
            if row and "Detailing" in row[1]:
                print("✓ CHECK constraint already includes 'Detailing', skipping")
            else:
                # Drop old constraint if it exists
                if row:
                    conn.execute(
                        text("ALTER TABLE service_records DROP CONSTRAINT check_service_category")
                    )
                conn.execute(
                    text("""
                        ALTER TABLE service_records ADD CONSTRAINT check_service_category
                        CHECK (service_category IN ('Maintenance', 'Inspection', 'Collision', 'Upgrades', 'Detailing'))
                    """)
                )
                print("✓ CHECK constraint updated to include 'Detailing'")

        else:
            # SQLite: must rebuild the table

            # Check if Detailing is already in the constraint
            result = conn.execute(
                text("SELECT sql FROM sqlite_master WHERE type='table' AND name='service_records'")
            )
            table_sql_row = result.fetchone()
            if table_sql_row and "Detailing" in table_sql_row[0] and not has_tsb_column:
                print("✓ Already migrated, skipping")
                return

            # Create new table with updated schema
            print("→ Creating new service_records table with Detailing category...")
            conn.execute(text("DROP TABLE IF EXISTS service_records_new"))
            conn.execute(
                text("""
                    CREATE TABLE service_records_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        vin TEXT NOT NULL,
                        date TEXT NOT NULL,
                        mileage INTEGER,
                        service_type TEXT NOT NULL,
                        cost REAL,
                        notes TEXT,
                        vendor_name TEXT,
                        vendor_location TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        service_category TEXT,
                        insurance_claim TEXT,
                        FOREIGN KEY (vin) REFERENCES vehicles (vin) ON DELETE CASCADE,
                        CONSTRAINT check_service_category CHECK (service_category IN ('Maintenance', 'Inspection', 'Collision', 'Upgrades', 'Detailing'))
                    )
                """)
            )

            # Copy data from old table (excluding tsb_id column)
            print("→ Migrating existing service records...")
            conn.execute(
                text("""
                    INSERT INTO service_records_new (
                        id, vin, date, mileage, service_type, cost, notes,
                        vendor_name, vendor_location, created_at, service_category, insurance_claim
                    )
                    SELECT
                        id, vin, date, mileage, service_type, cost, notes,
                        vendor_name, vendor_location, created_at, service_category, insurance_claim
                    FROM service_records
                """)
            )

            migrated_count = conn.execute(text("SELECT COUNT(*) FROM service_records_new")).scalar()
            print(f"✓ Migrated {migrated_count} service records")

            # Drop old table and rename new one
            print("→ Replacing old table...")
            conn.execute(text("DROP TABLE service_records"))
            conn.execute(text("ALTER TABLE service_records_new RENAME TO service_records"))

            # Recreate indexes
            print("→ Recreating indexes...")
            conn.execute(text("CREATE INDEX idx_service_records_vin ON service_records (vin)"))
            conn.execute(text("CREATE INDEX idx_service_records_date ON service_records (date)"))

        # Verify
        inspector = inspect(engine)
        final_columns = {col["name"] for col in inspector.get_columns("service_records")}
        if "tsb_id" not in final_columns:
            print("✓ TSB column verified removed")

        print("\nMigration 026 completed successfully")


def rollback(engine=None):
    """Rollback migration 026.

    WARNING: This will restore the TSB column but all data will be lost.
    Service category 'Detailing' will be removed from constraint.
    """
    if engine is None:
        engine = _get_fallback_engine()

    dialect = engine.dialect.name

    with engine.begin() as conn:
        print("\n=== Rolling back Migration 026 ===\n")

        if dialect == "postgresql":
            # Add TSB column back
            conn.execute(text("ALTER TABLE service_records ADD COLUMN tsb_id INTEGER"))
            # Update constraint
            result = conn.execute(
                text("""
                    SELECT conname FROM pg_constraint
                    WHERE conrelid = 'service_records'::regclass
                    AND contype = 'c' AND conname = 'check_service_category'
                """)
            )
            if result.fetchone():
                conn.execute(
                    text("ALTER TABLE service_records DROP CONSTRAINT check_service_category")
                )
            conn.execute(
                text("""
                    ALTER TABLE service_records ADD CONSTRAINT check_service_category
                    CHECK (service_category IN ('Maintenance', 'Inspection', 'Collision', 'Upgrades'))
                """)
            )
            # Null out any Detailing categories
            conn.execute(
                text(
                    "UPDATE service_records SET service_category = NULL WHERE service_category = 'Detailing'"
                )
            )
            print("✓ Migration 026 rolled back on PostgreSQL")
        else:
            # SQLite: rebuild table
            conn.execute(
                text("""
                    CREATE TABLE service_records_old (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        vin TEXT NOT NULL,
                        date TEXT NOT NULL,
                        mileage INTEGER,
                        service_type TEXT NOT NULL,
                        cost REAL,
                        notes TEXT,
                        vendor_name TEXT,
                        vendor_location TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        service_category TEXT,
                        insurance_claim TEXT,
                        tsb_id INTEGER,
                        FOREIGN KEY (vin) REFERENCES vehicles (vin) ON DELETE CASCADE,
                        FOREIGN KEY (tsb_id) REFERENCES tsbs (id) ON DELETE SET NULL,
                        CONSTRAINT check_service_category CHECK (service_category IN ('Maintenance', 'Inspection', 'Collision', 'Upgrades'))
                    )
                """)
            )
            conn.execute(
                text("""
                    INSERT INTO service_records_old (
                        id, vin, date, mileage, service_type, cost, notes,
                        vendor_name, vendor_location, created_at, service_category, insurance_claim, tsb_id
                    )
                    SELECT
                        id, vin, date, mileage, service_type, cost, notes,
                        vendor_name, vendor_location, created_at,
                        CASE WHEN service_category = 'Detailing' THEN NULL ELSE service_category END,
                        insurance_claim,
                        NULL
                    FROM service_records
                """)
            )
            conn.execute(text("DROP TABLE service_records"))
            conn.execute(text("ALTER TABLE service_records_old RENAME TO service_records"))
            conn.execute(text("CREATE INDEX idx_service_records_vin ON service_records (vin)"))
            conn.execute(text("CREATE INDEX idx_service_records_date ON service_records (date)"))
            print("✓ Migration 026 rolled back on SQLite")

        print("   WARNING: Any records with 'Detailing' category have been set to NULL")


if __name__ == "__main__":
    upgrade()

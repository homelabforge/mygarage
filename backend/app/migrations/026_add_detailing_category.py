"""Migration 026: Add Detailing category and repurpose TSB column.

This migration:
1. Drops the unused TSB column from service_records table
2. Adds service_category column with CHECK constraint including 'Detailing'
3. Updates existing service_category constraint to include 'Detailing'

Since the TSB column is unused and the TSB feature has been removed,
we drop it and ensure the service_category column has the correct constraint.
"""

import sqlite3
from pathlib import Path


def get_db_path() -> Path:
    """Get database file path."""
    data_dir = Path("/data")
    if data_dir.exists():
        return data_dir / "mygarage.db"
    return Path("mygarage.db")


def upgrade():
    """Run migration 026."""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        print("\n=== Migration 026: Add Detailing Category ===\n")

        # Check if TSB column exists
        cursor.execute("PRAGMA table_info(service_records)")
        columns = {row[1]: row for row in cursor.fetchall()}
        has_tsb_column = "tsb_id" in columns

        if has_tsb_column:
            print("ℹ Found unused TSB column - will be dropped during table recreation")

        # Get current table schema
        cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='service_records'"
        )
        result = cursor.fetchone()
        if not result:
            raise Exception("service_records table not found")

        # Create new table with updated schema
        # Drop TSB column, ensure service_category has Detailing
        print("→ Creating new service_records table with Detailing category...")
        cursor.execute("""
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

        # Copy data from old table (excluding tsb_id column)
        print("→ Migrating existing service records...")
        cursor.execute("""
            INSERT INTO service_records_new (
                id, vin, date, mileage, service_type, cost, notes,
                vendor_name, vendor_location, created_at, service_category, insurance_claim
            )
            SELECT
                id, vin, date, mileage, service_type, cost, notes,
                vendor_name, vendor_location, created_at, service_category, insurance_claim
            FROM service_records
        """)

        migrated_count = cursor.rowcount
        print(f"✓ Migrated {migrated_count} service records")

        # Drop old table and rename new one
        print("→ Replacing old table...")
        cursor.execute("DROP TABLE service_records")
        cursor.execute("ALTER TABLE service_records_new RENAME TO service_records")

        # Recreate indexes
        print("→ Recreating indexes...")
        cursor.execute("CREATE INDEX idx_service_records_vin ON service_records (vin)")
        cursor.execute(
            "CREATE INDEX idx_service_records_date ON service_records (date)"
        )

        # Verify the new constraint
        cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='service_records'"
        )
        table_sql = cursor.fetchone()[0]

        if "Detailing" in table_sql and "check_service_category" in table_sql:
            print("✓ CHECK constraint verified: includes 'Detailing'")
        else:
            raise Exception(
                "CHECK constraint verification failed - 'Detailing' not found"
            )

        # Verify no TSB column exists
        cursor.execute("PRAGMA table_info(service_records)")
        new_columns = {row[1]: row for row in cursor.fetchall()}
        if "tsb_id" not in new_columns:
            print("✓ TSB column successfully removed")
        else:
            raise Exception("TSB column still exists after migration")

        conn.commit()
        print("\n✅ Migration 026 completed successfully\n")
        print(f"   - Service records migrated: {migrated_count}")
        print("   - TSB column removed")
        print("   - Detailing category added to constraint")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ Migration 026 failed: {e}\n")
        raise

    finally:
        conn.close()


def rollback():
    """Rollback migration 026.

    WARNING: This will restore the TSB column but all data will be lost.
    Service category 'Detailing' will be removed from constraint.
    """
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        print("\n=== Rolling back Migration 026 ===\n")

        # Create table with old schema (including TSB column)
        print("→ Recreating table with TSB column...")
        cursor.execute("""
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

        # Copy data back
        print("→ Restoring service records...")
        cursor.execute("""
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

        # Drop new table and rename old one
        cursor.execute("DROP TABLE service_records")
        cursor.execute("ALTER TABLE service_records_old RENAME TO service_records")

        # Recreate indexes
        cursor.execute("CREATE INDEX idx_service_records_vin ON service_records (vin)")
        cursor.execute(
            "CREATE INDEX idx_service_records_date ON service_records (date)"
        )

        conn.commit()
        print("\n✅ Migration 026 rolled back successfully\n")
        print("   WARNING: Any records with 'Detailing' category have been set to NULL")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ Rollback failed: {e}\n")
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    upgrade()

"""Redesign service_records schema: separate category from specific service type.

Changes:
1. Rename service_type → service_category (keep nullable, keep CHECK constraint)
2. Rename description → service_type (increase to 100 chars, make required)
3. Set all service_type = 'General Service' (user updates via UI later)
4. Update indexes: idx_service_type → idx_service_category, add new idx_service_type

Background:
- Old schema: service_type stored category, description stored specific service
- New schema: service_category stores category, service_type stores specific service
- Migration preserves all data; users manually update service types post-migration

Created: 2025-12-29
"""

import sqlite3


def upgrade(db_path: str = "/data/mygarage.db"):
    """Redesign service_records schema with category/type separation."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        print("Service Records Schema Redesign Migration")
        print("=" * 60)

        # Step 1: Verify table exists
        print("\n[1/8] Verifying service_records table exists...")
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='service_records'"
        )
        if not cursor.fetchone():
            raise RuntimeError("service_records table does not exist")
        print("  ✓ Table verified")

        # Step 2: Count existing records
        cursor.execute("SELECT COUNT(*) FROM service_records")
        record_count = cursor.fetchone()[0]
        print(f"\n[2/8] Found {record_count} service records to migrate")

        # Step 3: Create backup table
        print("\n[3/8] Creating backup table...")
        cursor.execute("DROP TABLE IF EXISTS service_records_backup_20251229")
        cursor.execute(
            "CREATE TABLE service_records_backup_20251229 AS SELECT * FROM service_records"
        )
        print(f"  ✓ Backed up {record_count} records to service_records_backup_20251229")

        # Step 4: Create new table with updated schema
        print("\n[4/8] Creating new table with updated schema...")
        cursor.execute("""
            CREATE TABLE service_records_new (
                id INTEGER NOT NULL,
                vin VARCHAR(17) NOT NULL,
                date DATE NOT NULL,
                mileage INTEGER,
                service_type VARCHAR(100) NOT NULL DEFAULT 'General Service',
                cost NUMERIC(10, 2),
                notes TEXT,
                vendor_name VARCHAR(100),
                vendor_location VARCHAR(100),
                service_category VARCHAR(30),
                insurance_claim VARCHAR(50),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                PRIMARY KEY (id),
                CONSTRAINT check_service_category CHECK (service_category IN ('Maintenance', 'Inspection', 'Collision', 'Upgrades')),
                FOREIGN KEY(vin) REFERENCES vehicles (vin) ON DELETE CASCADE
            )
        """)
        print("  ✓ Created service_records_new table")

        # Step 5: Copy data with transformations
        print("\n[5/8] Migrating data with column transformations...")
        print("  • service_type → service_category (preserve values)")
        print("  • description → service_type (set all to 'General Service')")

        cursor.execute("""
            INSERT INTO service_records_new (
                id, vin, date, mileage, service_type, cost, notes,
                vendor_name, vendor_location, service_category, insurance_claim, created_at
            )
            SELECT
                id, vin, date, mileage,
                'General Service' as service_type,
                cost, notes, vendor_name, vendor_location,
                service_type as service_category,
                insurance_claim, created_at
            FROM service_records
        """)
        print(f"  ✓ Migrated {record_count} records")

        # Step 6: Drop old table and rename new table
        print("\n[6/8] Replacing old table...")
        cursor.execute("DROP TABLE service_records")
        cursor.execute("ALTER TABLE service_records_new RENAME TO service_records")
        print("  ✓ Table replaced")

        # Step 7: Recreate indexes
        print("\n[7/8] Recreating indexes...")

        # Basic indexes
        cursor.execute("CREATE INDEX idx_service_records_vin ON service_records(vin)")
        print("  ✓ idx_service_records_vin")

        cursor.execute("CREATE INDEX idx_service_records_date ON service_records(date)")
        print("  ✓ idx_service_records_date")

        # Composite index for common queries
        cursor.execute("CREATE INDEX idx_service_vin_date ON service_records(vin, date)")
        print("  ✓ idx_service_vin_date")

        # Mileage index
        cursor.execute("CREATE INDEX idx_service_mileage ON service_records(mileage)")
        print("  ✓ idx_service_mileage")

        # Category index (renamed from old service_type index)
        cursor.execute("CREATE INDEX idx_service_category ON service_records(service_category)")
        print("  ✓ idx_service_category (renamed from idx_service_type)")

        # NEW: Specific service type index
        cursor.execute("CREATE INDEX idx_service_type ON service_records(service_type)")
        print("  ✓ idx_service_type (NEW: for specific service filtering)")

        # Vendor index
        cursor.execute("CREATE INDEX idx_service_vendor ON service_records(vendor_name)")
        print("  ✓ idx_service_vendor")

        # Composite index for vehicle + category queries (renamed)
        cursor.execute(
            "CREATE INDEX idx_service_vin_category ON service_records(vin, service_category)"
        )
        print("  ✓ idx_service_vin_category (renamed from idx_service_vin_type)")

        # Step 8: Verification
        print("\n[8/8] Verification...")
        print("=" * 60)

        # Verify record count
        cursor.execute("SELECT COUNT(*) FROM service_records")
        new_count = cursor.fetchone()[0]
        print(f"\n✓ Record count: {new_count} (expected: {record_count})")

        if new_count != record_count:
            raise RuntimeError(f"Record count mismatch! Expected {record_count}, got {new_count}")

        # Verify all service_type values
        cursor.execute("SELECT COUNT(DISTINCT service_type) FROM service_records")
        distinct_service_types = cursor.fetchone()[0]
        print(f"✓ Distinct service_type values: {distinct_service_types} (expected: 1)")

        if distinct_service_types != 1:
            raise RuntimeError(
                f"Expected all service_type='General Service', found {distinct_service_types} distinct values"
            )

        # Verify service_category distribution
        cursor.execute("""
            SELECT service_category, COUNT(*) as count
            FROM service_records
            GROUP BY service_category
            ORDER BY service_category
        """)

        print("\n✓ Service category distribution:")
        category_counts = cursor.fetchall()
        for category, count in category_counts:
            category_label = category if category else "NULL"
            print(f"    {category_label}: {count}")

        # Verify indexes
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='service_records' ORDER BY name"
        )
        indexes = [row[0] for row in cursor.fetchall()]

        print(f"\n✓ Indexes created: {len(indexes)}")
        for idx in indexes:
            print(f"    {idx}")

        # Verify schema
        cursor.execute("PRAGMA table_info(service_records)")
        columns = {
            row[1]: {"type": row[2], "notnull": row[3], "default": row[4]}
            for row in cursor.fetchall()
        }

        print("\n✓ Schema verification:")
        print(
            f"    service_type: {columns['service_type']['type']} NOT NULL={columns['service_type']['notnull']}"
        )
        print(
            f"    service_category: {columns['service_category']['type']} NOT NULL={columns['service_category']['notnull']}"
        )

        # Verify foreign key
        cursor.execute("PRAGMA foreign_key_list(service_records)")
        fks = list(cursor.fetchall())
        print(f"\n✓ Foreign keys: {len(fks)}")
        for fk in fks:
            print(f"    {fk[2]}.{fk[3]} → {fk[4]}")

        # Verify CHECK constraint
        cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='service_records'"
        )
        table_sql = cursor.fetchone()[0]
        if "check_service_category" in table_sql and "CHECK (service_category IN" in table_sql:
            print("\n✓ CHECK constraint verified: check_service_category")
        else:
            raise RuntimeError(
                "CHECK constraint 'check_service_category' not found in table definition"
            )

        conn.commit()

        print("\n" + "=" * 60)
        print("MIGRATION COMPLETED SUCCESSFULLY")
        print("=" * 60)
        print(f"\n✓ Migrated {record_count} service records")
        print("✓ Renamed service_type → service_category")
        print("✓ Renamed description → service_type (all set to 'General Service')")
        print("✓ Recreated all indexes with updated names")
        print("✓ Backup available: service_records_backup_20251229")
        print("\nNEXT STEPS:")
        print("  1. Restart MyGarage application to load new schema")
        print("  2. Users should manually update service_type via UI")
        print("  3. Monitor logs for any schema-related errors")
        print("  4. Backup table can be dropped after verification period")

    except Exception as e:
        conn.rollback()
        print(f"\n✗ Migration failed: {e}")
        print("\nROLLBACK: To restore from backup, run:")
        print("  sqlite3 /data/mygarage.db")
        print("  DROP TABLE IF EXISTS service_records;")
        print("  ALTER TABLE service_records_backup_20251229 RENAME TO service_records;")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    upgrade()

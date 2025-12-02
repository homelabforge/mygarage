"""
Migration: Consolidate Collisions and Upgrades into Service Records

Changes:
1. Add insurance_claim field to service_records table
2. Migrate collision_records → service_records (service_type='Collision')
3. Migrate upgrade_records → service_records (service_type='Upgrades')
4. Create backup tables (collision_records_backup, upgrade_records_backup)
5. Drop original collision_records and upgrade_records tables

Service Types: Maintenance, Inspection, Collision, Upgrades
"""

import sqlite3
import os
from datetime import datetime

def migrate():
    db_path = os.environ.get('DATABASE_PATH', '/data/mygarage.db')

    print(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Step 1: Add insurance_claim column to service_records if it doesn't exist
        print("\n=== Step 1: Adding insurance_claim column to service_records ===")
        cursor.execute("PRAGMA table_info(service_records)")
        existing_columns = [row[1] for row in cursor.fetchall()]

        if 'insurance_claim' not in existing_columns:
            cursor.execute("ALTER TABLE service_records ADD COLUMN insurance_claim VARCHAR(50)")
            print("✓ Added insurance_claim column")
        else:
            print("✓ insurance_claim column already exists")

        conn.commit()

        # Step 2: Check if collision_records table exists
        print("\n=== Step 2: Checking for collision_records table ===")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='collision_records'")
        collision_table_exists = cursor.fetchone() is not None

        if collision_table_exists:
            # Count collision records
            cursor.execute("SELECT COUNT(*) FROM collision_records")
            collision_count = cursor.fetchone()[0]
            print(f"✓ Found {collision_count} collision records to migrate")

            if collision_count > 0:
                # Create backup table
                print("\n=== Creating collision_records_backup ===")
                cursor.execute("DROP TABLE IF EXISTS collision_records_backup")
                cursor.execute("CREATE TABLE collision_records_backup AS SELECT * FROM collision_records")
                print(f"✓ Backed up {collision_count} collision records")

                # Migrate collision records to service_records
                print("\n=== Migrating collision records to service_records ===")
                cursor.execute("""
                    INSERT INTO service_records (
                        vin, date, mileage, description, cost, notes,
                        vendor_name, insurance_claim, service_type, created_at
                    )
                    SELECT
                        vin, date, mileage, description, cost, notes,
                        repair_shop as vendor_name,
                        insurance_claim,
                        'Collision' as service_type,
                        created_at
                    FROM collision_records
                """)
                migrated_collision_count = cursor.rowcount
                print(f"✓ Migrated {migrated_collision_count} collision records")

                # Drop collision_records table
                print("\n=== Dropping collision_records table ===")
                cursor.execute("DROP TABLE collision_records")
                print("✓ Dropped collision_records table")
            else:
                print("✓ No collision records to migrate")
                # Still create empty backup and drop table
                cursor.execute("CREATE TABLE IF NOT EXISTS collision_records_backup AS SELECT * FROM collision_records")
                cursor.execute("DROP TABLE collision_records")
        else:
            print("✓ collision_records table does not exist (already migrated or never created)")

        conn.commit()

        # Step 3: Check if upgrade_records table exists
        print("\n=== Step 3: Checking for upgrade_records table ===")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='upgrade_records'")
        upgrade_table_exists = cursor.fetchone() is not None

        if upgrade_table_exists:
            # Count upgrade records
            cursor.execute("SELECT COUNT(*) FROM upgrade_records")
            upgrade_count = cursor.fetchone()[0]
            print(f"✓ Found {upgrade_count} upgrade records to migrate")

            if upgrade_count > 0:
                # Create backup table
                print("\n=== Creating upgrade_records_backup ===")
                cursor.execute("DROP TABLE IF EXISTS upgrade_records_backup")
                cursor.execute("CREATE TABLE upgrade_records_backup AS SELECT * FROM upgrade_records")
                print(f"✓ Backed up {upgrade_count} upgrade records")

                # Migrate upgrade records to service_records
                print("\n=== Migrating upgrade records to service_records ===")
                cursor.execute("""
                    INSERT INTO service_records (
                        vin, date, mileage, description, cost, notes,
                        vendor_name, service_type, created_at
                    )
                    SELECT
                        vin, date, mileage, description, cost, notes,
                        vendor_name,
                        'Upgrades' as service_type,
                        created_at
                    FROM upgrade_records
                """)
                migrated_upgrade_count = cursor.rowcount
                print(f"✓ Migrated {migrated_upgrade_count} upgrade records")

                # Drop upgrade_records table
                print("\n=== Dropping upgrade_records table ===")
                cursor.execute("DROP TABLE upgrade_records")
                print("✓ Dropped upgrade_records table")
            else:
                print("✓ No upgrade records to migrate")
                # Still create empty backup and drop table
                cursor.execute("CREATE TABLE IF NOT EXISTS upgrade_records_backup AS SELECT * FROM upgrade_records")
                cursor.execute("DROP TABLE upgrade_records")
        else:
            print("✓ upgrade_records table does not exist (already migrated or never created)")

        conn.commit()

        # Step 4: Verify migration
        print("\n=== Step 4: Verifying migration ===")
        cursor.execute("SELECT service_type, COUNT(*) FROM service_records GROUP BY service_type")
        type_counts = cursor.fetchall()

        print("\nService records by type:")
        for service_type, count in type_counts:
            print(f"  {service_type}: {count}")

        cursor.execute("SELECT COUNT(*) FROM service_records")
        total_count = cursor.fetchone()[0]
        print(f"\nTotal service records: {total_count}")

        print("\n=== Migration complete! ===")
        print("Summary:")
        print(f"  ✓ Added insurance_claim field to service_records")
        if collision_table_exists:
            print(f"  ✓ Migrated collision records to service_records")
            print(f"  ✓ Backed up and dropped collision_records table")
        if upgrade_table_exists:
            print(f"  ✓ Migrated upgrade records to service_records")
            print(f"  ✓ Backed up and dropped upgrade_records table")
        print(f"  ✓ Total service records: {total_count}")

    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()

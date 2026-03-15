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
    """Redesign service_records schema with category/type separation."""
    if engine is None:
        engine = _get_fallback_engine()

    dialect = engine.dialect.name

    with engine.begin() as conn:
        inspector = inspect(engine)

        if not inspector.has_table("service_records"):
            print("  service_records table does not exist, skipping")
            return

        existing_columns = {col["name"] for col in inspector.get_columns("service_records")}

        # Check if already migrated (service_category exists = already done)
        if "service_category" in existing_columns:
            print("  → service_records already has service_category, skipping")
            return

        print("Service Records Schema Redesign Migration")
        print("=" * 60)

        # Count existing records
        result = conn.execute(text("SELECT COUNT(*) FROM service_records"))
        record_count = result.scalar()
        print(f"\nFound {record_count} service records to migrate")

        if dialect == "postgresql":
            # PostgreSQL supports RENAME COLUMN and ALTER COLUMN directly

            # Create backup
            print("\nCreating backup table...")
            conn.execute(text("DROP TABLE IF EXISTS service_records_backup_20251229"))
            conn.execute(
                text(
                    "CREATE TABLE service_records_backup_20251229 AS SELECT * FROM service_records"
                )
            )
            print(f"  ✓ Backed up {record_count} records")

            # Rename service_type → service_category
            print("\nRenaming columns...")
            conn.execute(
                text("ALTER TABLE service_records RENAME COLUMN service_type TO service_category")
            )
            print("  ✓ service_type → service_category")

            # Rename description → service_type
            conn.execute(
                text("ALTER TABLE service_records RENAME COLUMN description TO service_type")
            )
            print("  ✓ description → service_type")

            # Alter service_type column: increase size and set NOT NULL with default
            conn.execute(
                text("ALTER TABLE service_records ALTER COLUMN service_type TYPE VARCHAR(100)")
            )
            conn.execute(
                text(
                    "ALTER TABLE service_records ALTER COLUMN service_type SET DEFAULT 'General Service'"
                )
            )
            # Set all to 'General Service'
            conn.execute(text("UPDATE service_records SET service_type = 'General Service'"))
            conn.execute(text("ALTER TABLE service_records ALTER COLUMN service_type SET NOT NULL"))
            print("  ✓ service_type set to VARCHAR(100) NOT NULL DEFAULT 'General Service'")

            # Drop old constraint and add new one
            result = conn.execute(
                text("""
                    SELECT conname FROM pg_constraint
                    WHERE conrelid = 'service_records'::regclass
                    AND contype = 'c'
                    AND conname = 'check_service_type'
                """)
            )
            if result.fetchone():
                conn.execute(text("ALTER TABLE service_records DROP CONSTRAINT check_service_type"))

            conn.execute(
                text("""
                    ALTER TABLE service_records ADD CONSTRAINT check_service_category
                    CHECK (service_category IN ('Maintenance', 'Inspection', 'Collision', 'Upgrades'))
                """)
            )
            print("  ✓ CHECK constraint updated to check_service_category")

            # Update indexes
            print("\nRecreating indexes...")
            # Drop old indexes if they exist (ignore errors)
            for idx in ["idx_service_type", "idx_service_vin_type"]:
                try:
                    conn.execute(text(f"DROP INDEX IF EXISTS {idx}"))
                except Exception:
                    pass

            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_service_category ON service_records(service_category)"
                )
            )
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS idx_service_type ON service_records(service_type)")
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_service_vin_category ON service_records(vin, service_category)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_service_vin_date ON service_records(vin, date)"
                )
            )
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS idx_service_mileage ON service_records(mileage)")
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_service_vendor ON service_records(vendor_name)"
                )
            )
            print("  ✓ All indexes updated")

        else:
            # SQLite: must rebuild the table

            # Create backup table
            print("\nCreating backup table...")
            conn.execute(text("DROP TABLE IF EXISTS service_records_backup_20251229"))
            conn.execute(
                text(
                    "CREATE TABLE service_records_backup_20251229 AS SELECT * FROM service_records"
                )
            )
            print(f"  ✓ Backed up {record_count} records")

            # Create new table with updated schema
            print("\nCreating new table with updated schema...")
            conn.execute(text("DROP TABLE IF EXISTS service_records_new"))
            conn.execute(
                text("""
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
            )

            # Copy data with transformations
            print("\nMigrating data with column transformations...")
            conn.execute(
                text("""
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
            )

            # Replace table
            conn.execute(text("DROP TABLE service_records"))
            conn.execute(text("ALTER TABLE service_records_new RENAME TO service_records"))

            # Recreate indexes
            print("\nRecreating indexes...")
            conn.execute(text("CREATE INDEX idx_service_records_vin ON service_records(vin)"))
            conn.execute(text("CREATE INDEX idx_service_records_date ON service_records(date)"))
            conn.execute(text("CREATE INDEX idx_service_vin_date ON service_records(vin, date)"))
            conn.execute(text("CREATE INDEX idx_service_mileage ON service_records(mileage)"))
            conn.execute(
                text("CREATE INDEX idx_service_category ON service_records(service_category)")
            )
            conn.execute(text("CREATE INDEX idx_service_type ON service_records(service_type)"))
            conn.execute(text("CREATE INDEX idx_service_vendor ON service_records(vendor_name)"))
            conn.execute(
                text(
                    "CREATE INDEX idx_service_vin_category ON service_records(vin, service_category)"
                )
            )

        # Verification
        result = conn.execute(text("SELECT COUNT(*) FROM service_records"))
        new_count = result.scalar()
        print(f"\n✓ Record count: {new_count} (expected: {record_count})")

        if new_count != record_count:
            raise RuntimeError(f"Record count mismatch! Expected {record_count}, got {new_count}")

        print("\n" + "=" * 60)
        print("MIGRATION COMPLETED SUCCESSFULLY")
        print("=" * 60)


if __name__ == "__main__":
    upgrade()

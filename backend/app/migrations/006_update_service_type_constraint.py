"""Update service_type CHECK constraint to include Collision and Upgrades."""

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
    """Update the service_type check constraint."""
    if engine is None:
        engine = _get_fallback_engine()

    dialect = engine.dialect.name

    with engine.begin() as conn:
        inspector = inspect(engine)

        if not inspector.has_table("service_records"):
            print("  service_records table does not exist, skipping")
            return

        if dialect == "postgresql":
            # PostgreSQL: can alter constraints directly
            # Check if constraint already has 'Collision'
            result = conn.execute(
                text("""
                    SELECT conname, pg_get_constraintdef(oid)
                    FROM pg_constraint
                    WHERE conrelid = 'service_records'::regclass
                    AND contype = 'c'
                    AND conname = 'check_service_type'
                """)
            )
            row = result.fetchone()
            if row and "Collision" in row[1]:
                print("✓ service_type constraint already updated, skipping")
                return

            # Drop old constraint if it exists
            if row:
                conn.execute(text("ALTER TABLE service_records DROP CONSTRAINT check_service_type"))

            # Add updated constraint
            conn.execute(
                text("""
                    ALTER TABLE service_records ADD CONSTRAINT check_service_type
                    CHECK (service_type IN ('Maintenance', 'Repair', 'Inspection', 'Collision', 'Upgrades'))
                """)
            )
            print("✓ Successfully updated service_type constraint")

        else:
            # SQLite: must rebuild the table to change constraints
            # Check if constraint is already updated (idempotency guard)
            result = conn.execute(
                text("SELECT sql FROM sqlite_master WHERE type='table' AND name='service_records'")
            )
            row = result.fetchone()
            if row and "'Collision'" in row[0]:
                print("✓ service_type constraint already updated, skipping")
                return

            # Clean up any leftover temp table from a previous failed run
            conn.execute(text("DROP TABLE IF EXISTS service_records_new"))

            # 1. Create new table with updated constraint
            conn.execute(
                text("""
                    CREATE TABLE service_records_new (
                        id INTEGER NOT NULL,
                        vin VARCHAR(17) NOT NULL,
                        date DATE NOT NULL,
                        mileage INTEGER,
                        description VARCHAR(200) NOT NULL,
                        cost NUMERIC(10, 2),
                        notes TEXT,
                        vendor_name VARCHAR(100),
                        vendor_location VARCHAR(100),
                        service_type VARCHAR(30),
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                        insurance_claim VARCHAR(50),
                        PRIMARY KEY (id),
                        CONSTRAINT check_service_type CHECK (service_type IN ('Maintenance', 'Repair', 'Inspection', 'Collision', 'Upgrades')),
                        FOREIGN KEY(vin) REFERENCES vehicles (vin) ON DELETE CASCADE
                    )
                """)
            )

            # 2. Copy data from old table to new table
            conn.execute(text("INSERT INTO service_records_new SELECT * FROM service_records"))

            # 3. Drop old table
            conn.execute(text("DROP TABLE service_records"))

            # 4. Rename new table to original name
            conn.execute(text("ALTER TABLE service_records_new RENAME TO service_records"))

            # 5. Recreate indexes
            conn.execute(text("CREATE INDEX idx_service_records_vin ON service_records (vin)"))
            conn.execute(text("CREATE INDEX idx_service_records_date ON service_records (date)"))

            print("✓ Successfully updated service_type constraint")


if __name__ == "__main__":
    upgrade()

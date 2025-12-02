"""Update service_type CHECK constraint to include Collision and Upgrades."""

import sqlite3


def upgrade(db_path: str = "/data/mygarage.db"):
    """Update the service_type check constraint."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # SQLite doesn't support ALTER TABLE to modify constraints
        # We need to recreate the table

        # 1. Create new table with updated constraint
        cursor.execute("""
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

        # 2. Copy data from old table to new table
        cursor.execute("""
            INSERT INTO service_records_new
            SELECT * FROM service_records
        """)

        # 3. Drop old table
        cursor.execute("DROP TABLE service_records")

        # 4. Rename new table to original name
        cursor.execute("ALTER TABLE service_records_new RENAME TO service_records")

        # 5. Recreate indexes
        cursor.execute("CREATE INDEX idx_service_records_vin ON service_records (vin)")
        cursor.execute("CREATE INDEX idx_service_records_date ON service_records (date)")

        conn.commit()
        print("✓ Successfully updated service_type constraint")

    except Exception as e:
        conn.rollback()
        print(f"✗ Error updating constraint: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    upgrade()

"""Maintenance system overhaul - new tables for service visits, vendors, and schedule items."""

import os
from pathlib import Path

from sqlalchemy import create_engine, text


def upgrade():
    """Create new maintenance system tables and migrate existing data."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    # Create engine
    engine = create_engine(database_url)

    with engine.begin() as conn:
        # =================================================================
        # PHASE 1: Create new tables
        # =================================================================

        # 1. Create vendors table
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='vendors'")
        )
        if not result.fetchone():
            print("Creating vendors table...")
            conn.execute(
                text("""
                CREATE TABLE vendors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(100) NOT NULL UNIQUE,
                    address TEXT,
                    city VARCHAR(100),
                    state VARCHAR(50),
                    zip_code VARCHAR(20),
                    phone VARCHAR(20),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME
                )
            """)
            )
            conn.execute(text("CREATE INDEX idx_vendors_name ON vendors(name)"))
            print("  Created vendors table")
        else:
            print("  vendors table already exists")

        # 2. Create maintenance_schedule_items table
        result = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='maintenance_schedule_items'"
            )
        )
        if not result.fetchone():
            print("Creating maintenance_schedule_items table...")
            conn.execute(
                text("""
                CREATE TABLE maintenance_schedule_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vin VARCHAR(17) NOT NULL,
                    name VARCHAR(100) NOT NULL,
                    component_category VARCHAR(50) NOT NULL,
                    item_type VARCHAR(20) NOT NULL,
                    interval_months INTEGER,
                    interval_miles INTEGER,
                    source VARCHAR(20) NOT NULL,
                    template_item_id VARCHAR(100),
                    last_performed_date DATE,
                    last_performed_mileage INTEGER,
                    last_service_line_item_id INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME,
                    FOREIGN KEY (vin) REFERENCES vehicles(vin) ON DELETE CASCADE
                )
            """)
            )
            conn.execute(
                text("CREATE INDEX idx_maintenance_schedule_vin ON maintenance_schedule_items(vin)")
            )
            conn.execute(
                text(
                    "CREATE INDEX idx_maintenance_schedule_category ON maintenance_schedule_items(component_category)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX idx_maintenance_schedule_type ON maintenance_schedule_items(item_type)"
                )
            )
            print("  Created maintenance_schedule_items table")
        else:
            print("  maintenance_schedule_items table already exists")

        # 3. Create service_visits table
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='service_visits'")
        )
        if not result.fetchone():
            print("Creating service_visits table...")
            conn.execute(
                text("""
                CREATE TABLE service_visits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vin VARCHAR(17) NOT NULL,
                    vendor_id INTEGER,
                    date DATE NOT NULL,
                    mileage INTEGER,
                    total_cost DECIMAL(10,2),
                    notes TEXT,
                    service_category VARCHAR(30),
                    insurance_claim_number VARCHAR(50),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME,
                    FOREIGN KEY (vin) REFERENCES vehicles(vin) ON DELETE CASCADE,
                    FOREIGN KEY (vendor_id) REFERENCES vendors(id)
                )
            """)
            )
            conn.execute(text("CREATE INDEX idx_service_visits_vin ON service_visits(vin)"))
            conn.execute(text("CREATE INDEX idx_service_visits_date ON service_visits(date)"))
            conn.execute(
                text("CREATE INDEX idx_service_visits_vendor ON service_visits(vendor_id)")
            )
            conn.execute(
                text("CREATE INDEX idx_service_visits_vin_date ON service_visits(vin, date)")
            )
            print("  Created service_visits table")
        else:
            print("  service_visits table already exists")

        # 4. Create service_line_items table
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='service_line_items'")
        )
        if not result.fetchone():
            print("Creating service_line_items table...")
            conn.execute(
                text("""
                CREATE TABLE service_line_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    visit_id INTEGER NOT NULL,
                    schedule_item_id INTEGER,
                    description VARCHAR(200) NOT NULL,
                    cost DECIMAL(10,2),
                    notes TEXT,
                    is_inspection BOOLEAN DEFAULT 0,
                    inspection_result VARCHAR(20),
                    inspection_severity VARCHAR(10),
                    triggered_by_inspection_id INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (visit_id) REFERENCES service_visits(id) ON DELETE CASCADE,
                    FOREIGN KEY (schedule_item_id) REFERENCES maintenance_schedule_items(id),
                    FOREIGN KEY (triggered_by_inspection_id) REFERENCES service_line_items(id)
                )
            """)
            )
            conn.execute(
                text("CREATE INDEX idx_service_line_items_visit ON service_line_items(visit_id)")
            )
            conn.execute(
                text(
                    "CREATE INDEX idx_service_line_items_schedule ON service_line_items(schedule_item_id)"
                )
            )
            print("  Created service_line_items table")
        else:
            print("  service_line_items table already exists")

        # 5. Create vendor_price_history table
        result = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='vendor_price_history'"
            )
        )
        if not result.fetchone():
            print("Creating vendor_price_history table...")
            conn.execute(
                text("""
                CREATE TABLE vendor_price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vendor_id INTEGER NOT NULL,
                    schedule_item_id INTEGER NOT NULL,
                    service_line_item_id INTEGER NOT NULL,
                    date DATE NOT NULL,
                    cost DECIMAL(10,2) NOT NULL,
                    FOREIGN KEY (vendor_id) REFERENCES vendors(id),
                    FOREIGN KEY (schedule_item_id) REFERENCES maintenance_schedule_items(id),
                    FOREIGN KEY (service_line_item_id) REFERENCES service_line_items(id)
                )
            """)
            )
            conn.execute(
                text("CREATE INDEX idx_vendor_price_vendor ON vendor_price_history(vendor_id)")
            )
            conn.execute(
                text(
                    "CREATE INDEX idx_vendor_price_schedule ON vendor_price_history(schedule_item_id)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX idx_vendor_price_vendor_schedule ON vendor_price_history(vendor_id, schedule_item_id)"
                )
            )
            print("  Created vendor_price_history table")
        else:
            print("  vendor_price_history table already exists")

        # =================================================================
        # PHASE 2: Migrate existing data
        # =================================================================

        # Check if service_records table exists and has data
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='service_records'")
        )
        if result.fetchone():
            # Check if migration already ran (look for migrated visits)
            result = conn.execute(text("SELECT COUNT(*) FROM service_visits"))
            existing_visits = result.scalar()

            if existing_visits == 0:
                print("\nMigrating existing service records...")

                # 2a. Extract unique vendors from service_records
                print("  Extracting vendors from service_records...")
                result = conn.execute(
                    text("""
                    SELECT DISTINCT vendor_name, vendor_location
                    FROM service_records
                    WHERE vendor_name IS NOT NULL AND vendor_name != ''
                """)
                )
                vendors = result.fetchall()

                vendor_map = {}
                for vendor_name, vendor_location in vendors:
                    # Parse location into city/state if possible
                    city = None
                    state = None
                    if vendor_location:
                        parts = vendor_location.split(",")
                        if len(parts) >= 2:
                            city = parts[0].strip()
                            state = parts[1].strip()
                        elif len(parts) == 1:
                            city = parts[0].strip()

                    # Insert vendor
                    conn.execute(
                        text("""
                        INSERT OR IGNORE INTO vendors (name, city, state)
                        VALUES (:name, :city, :state)
                    """),
                        {"name": vendor_name, "city": city, "state": state},
                    )

                    # Get vendor ID
                    result = conn.execute(
                        text("SELECT id FROM vendors WHERE name = :name"),
                        {"name": vendor_name},
                    )
                    row = result.fetchone()
                    if row:
                        vendor_map[vendor_name] = row[0]

                print(f"    Created {len(vendor_map)} vendor(s)")

                # 2b. Migrate service_records to service_visits and service_line_items
                print("  Migrating service records to visits...")
                result = conn.execute(
                    text("""
                    SELECT id, vin, date, mileage, service_type, cost, notes,
                           vendor_name, service_category, insurance_claim, created_at
                    FROM service_records
                    ORDER BY date
                """)
                )
                records = result.fetchall()

                migrated = 0
                for record in records:
                    (
                        _record_id,
                        vin,
                        date,
                        mileage,
                        service_type,
                        cost,
                        notes,
                        vendor_name,
                        service_category,
                        insurance_claim,
                        created_at,
                    ) = record

                    # Get vendor_id if exists
                    vendor_id = vendor_map.get(vendor_name) if vendor_name else None

                    # Create service_visit
                    conn.execute(
                        text("""
                        INSERT INTO service_visits
                        (vin, vendor_id, date, mileage, total_cost, notes,
                         service_category, insurance_claim_number, created_at)
                        VALUES (:vin, :vendor_id, :date, :mileage, :cost, :notes,
                                :category, :insurance, :created_at)
                    """),
                        {
                            "vin": vin,
                            "vendor_id": vendor_id,
                            "date": date,
                            "mileage": mileage,
                            "cost": cost,
                            "notes": notes,
                            "category": service_category,
                            "insurance": insurance_claim,
                            "created_at": created_at,
                        },
                    )

                    # Get the visit ID
                    result = conn.execute(text("SELECT last_insert_rowid()"))
                    visit_id = result.scalar()

                    # Determine if this is an inspection based on service type
                    is_inspection = (
                        service_category == "Inspection"
                        or "inspection" in (service_type or "").lower()
                    )

                    # Create service_line_item
                    conn.execute(
                        text("""
                        INSERT INTO service_line_items
                        (visit_id, description, cost, is_inspection, created_at)
                        VALUES (:visit_id, :description, :cost, :is_inspection, :created_at)
                    """),
                        {
                            "visit_id": visit_id,
                            "description": service_type or "General Service",
                            "cost": cost,
                            "is_inspection": 1 if is_inspection else 0,
                            "created_at": created_at,
                        },
                    )

                    migrated += 1

                print(f"    Migrated {migrated} service record(s)")
            else:
                print(f"\n  Service records already migrated ({existing_visits} visits exist)")

        # 2c. Convert reminders to maintenance_schedule_items
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='reminders'")
        )
        if result.fetchone():
            # Check if schedule items already exist for this vehicle
            result = conn.execute(text("SELECT COUNT(*) FROM maintenance_schedule_items"))
            existing_items = result.scalar()

            if existing_items == 0:
                print("\nConverting reminders to schedule items...")
                result = conn.execute(
                    text("""
                    SELECT id, vin, description, due_date, due_mileage,
                           is_recurring, recurrence_days, recurrence_miles, notes
                    FROM reminders
                    WHERE is_completed = 0
                """)
                )
                reminders = result.fetchall()

                converted = 0
                for reminder in reminders:
                    (
                        _reminder_id,
                        vin,
                        description,
                        _due_date,
                        _due_mileage,
                        _is_recurring,
                        recurrence_days,
                        recurrence_miles,
                        _notes,
                    ) = reminder

                    # Calculate interval from recurrence
                    interval_months = None
                    if recurrence_days:
                        interval_months = recurrence_days // 30

                    # Determine component category from description
                    component_category = categorize_service(description)

                    # Determine if inspection
                    item_type = "inspection" if "inspection" in description.lower() else "service"

                    conn.execute(
                        text("""
                        INSERT INTO maintenance_schedule_items
                        (vin, name, component_category, item_type, interval_months,
                         interval_miles, source, created_at)
                        VALUES (:vin, :name, :category, :type, :months,
                                :miles, 'migrated_reminder', CURRENT_TIMESTAMP)
                    """),
                        {
                            "vin": vin,
                            "name": description,
                            "category": component_category,
                            "type": item_type,
                            "months": interval_months,
                            "miles": recurrence_miles,
                        },
                    )
                    converted += 1

                print(f"  Converted {converted} reminder(s) to schedule items")

                # Delete converted reminders (non-completed ones that were converted)
                if converted > 0:
                    print("  Deleting converted reminders...")
                    conn.execute(text("DELETE FROM reminders WHERE is_completed = 0"))
                    print(f"    Deleted {converted} reminder(s)")
            else:
                print(f"\n  Schedule items already exist ({existing_items} items)")

        print("\nMaintenance system overhaul complete")


def categorize_service(description: str) -> str:
    """Categorize a service description into a component category."""
    desc_lower = description.lower()

    if any(w in desc_lower for w in ["oil", "engine", "spark", "belt", "timing"]):
        return "Engine"
    if any(w in desc_lower for w in ["transmission", "trans"]):
        return "Transmission"
    if any(w in desc_lower for w in ["brake", "rotor", "pad"]):
        return "Brakes"
    if any(w in desc_lower for w in ["tire", "wheel", "rotation", "alignment"]):
        return "Tires"
    if any(w in desc_lower for w in ["battery", "alternator", "electrical", "light"]):
        return "Electrical"
    if any(w in desc_lower for w in ["ac", "a/c", "heater", "hvac", "climate", "cabin"]):
        return "HVAC"
    if any(w in desc_lower for w in ["fluid", "coolant", "antifreeze"]):
        return "Fluids"
    if any(w in desc_lower for w in ["suspension", "shock", "strut", "spring"]):
        return "Suspension"
    if any(w in desc_lower for w in ["body", "paint", "dent", "bumper", "glass"]):
        return "Body/Exterior"
    if any(w in desc_lower for w in ["interior", "seat", "carpet", "upholster"]):
        return "Interior"
    if any(w in desc_lower for w in ["exhaust", "muffler", "catalytic"]):
        return "Exhaust"
    if any(w in desc_lower for w in ["fuel", "injector", "pump"]):
        return "Fuel System"

    return "Other"


if __name__ == "__main__":
    upgrade()

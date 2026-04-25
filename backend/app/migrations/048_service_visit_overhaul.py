"""Service visit overhaul Phase 1: per-line-item category + vehicle_reminders table."""

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
    """Add category to service_line_items, create vehicle_reminders table."""
    if engine is None:
        engine = _get_fallback_engine()

    is_postgres = engine.dialect.name == "postgresql"
    pk_type = "SERIAL PRIMARY KEY" if is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts_type = "TIMESTAMP" if is_postgres else "DATETIME"

    with engine.begin() as conn:
        # 1. Add category column to service_line_items (idempotent)
        cols = [c["name"] for c in inspect(engine).get_columns("service_line_items")]
        if "category" not in cols:
            print("Adding category column to service_line_items...")
            conn.execute(text("ALTER TABLE service_line_items ADD COLUMN category VARCHAR(30)"))
            print("✓ Added category column")
        else:
            print("✓ category column already exists on service_line_items")

        # 2. Backfill: copy visit-level service_category down to each line item
        result = conn.execute(
            text("SELECT COUNT(*) FROM service_line_items WHERE category IS NULL")
        )
        null_count = result.scalar() or 0
        if null_count > 0:
            print(f"Backfilling category on {null_count} line items...")
            conn.execute(
                text("""
                    UPDATE service_line_items
                    SET category = (
                        SELECT service_category FROM service_visits
                        WHERE service_visits.id = service_line_items.visit_id
                    )
                    WHERE category IS NULL
                """)
            )
            print("✓ Backfilled category from visit-level service_category")
        else:
            print("✓ No line items need category backfill")

        # 3. Create vehicle_reminders table (idempotent)
        if not inspect(engine).has_table("vehicle_reminders"):
            print("Creating vehicle_reminders table...")
            conn.execute(
                text(f"""
                    CREATE TABLE vehicle_reminders (
                        id               {pk_type},
                        vin              VARCHAR(17)  NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
                        line_item_id     INTEGER      REFERENCES service_line_items(id) ON DELETE SET NULL,
                        title            VARCHAR(200) NOT NULL,
                        reminder_type    VARCHAR(10)  NOT NULL
                                         CHECK (reminder_type IN ('date','mileage','both','smart')),
                        due_date         DATE,
                        due_mileage      INTEGER      CHECK (due_mileage > 0),
                        status           VARCHAR(10)  NOT NULL DEFAULT 'pending'
                                         CHECK (status IN ('pending','done','dismissed')),
                        notes            TEXT,
                        last_notified_at {ts_type},
                        created_at       {ts_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at       {ts_type} NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """)
            )
            print("✓ Created vehicle_reminders table")
        else:
            print("✓ vehicle_reminders table already exists")

        # Indexes are OUTSIDE the has_table block so a crash-restart re-run still applies them.
        # IF NOT EXISTS makes each index creation idempotent independently.
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_reminders_vin_status "
                "ON vehicle_reminders (vin, status)"
            )
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_reminders_due_date ON vehicle_reminders (due_date)")
        )
        # Fresh installs on 2.26.2+ already have due_mileage_km (canonical) from
        # Base.metadata.create_all + mig053; the legacy due_mileage column never
        # exists. Only create the legacy index if the column is actually there.
        reminder_cols = {c["name"] for c in inspect(engine).get_columns("vehicle_reminders")}
        if "due_mileage" in reminder_cols:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_reminders_due_mileage "
                    "ON vehicle_reminders (due_mileage)"
                )
            )
        print("✓ Indexes verified on vehicle_reminders")

        # DO NOT drop maintenance_schedule_items or maintenance_templates in Phase 1.
        # DO NOT touch service_category on service_visits (still read by analytics/calendar).
        # schedule_item_id on service_line_items stays — Phase 2 removes it.


if __name__ == "__main__":
    upgrade()

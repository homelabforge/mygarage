"""Phase 2: Remove maintenance schedule system, vendor price history, schedule_item_id FK."""

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
    """Drop maintenance schedule tables, vendor_price_history, and schedule_item_id FK."""
    if engine is None:
        engine = _get_fallback_engine()

    is_postgres = engine.dialect.name == "postgresql"

    with engine.begin() as conn:
        insp = inspect(conn)

        # 1. Drop vendor_price_history first (depends on maintenance_schedule_items)
        if insp.has_table("vendor_price_history"):
            print("Dropping vendor_price_history table...")
            conn.execute(text("DROP TABLE vendor_price_history"))
            print("  Dropped vendor_price_history")
        else:
            print("  vendor_price_history already dropped")

        # Clear inspect cache after DDL changes
        insp = inspect(conn)

        # 2. Drop schedule_item_id from service_line_items
        cols = [c["name"] for c in insp.get_columns("service_line_items")]
        if "schedule_item_id" in cols:
            if is_postgres:
                # PostgreSQL: ALTER TABLE DROP COLUMN
                print("Dropping schedule_item_id from service_line_items (PostgreSQL)...")
                conn.execute(text("ALTER TABLE service_line_items DROP COLUMN schedule_item_id"))
            else:
                # SQLite: table recreate pattern (no DROP COLUMN before 3.35)
                print("Dropping schedule_item_id from service_line_items (SQLite recreate)...")

                # Get current columns minus schedule_item_id
                current_cols = inspect(conn).get_columns("service_line_items")
                keep_cols = [c["name"] for c in current_cols if c["name"] != "schedule_item_id"]
                cols_csv = ", ".join(keep_cols)

                conn.execute(
                    text(f"""
                    CREATE TABLE service_line_items_new AS
                    SELECT {cols_csv} FROM service_line_items
                """)
                )
                conn.execute(text("DROP TABLE service_line_items"))
                conn.execute(
                    text("ALTER TABLE service_line_items_new RENAME TO service_line_items")
                )

                # Recreate indexes that existed on the original table
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_service_line_items_visit "
                        "ON service_line_items (visit_id)"
                    )
                )
            print("  Dropped schedule_item_id column")
        else:
            print("  schedule_item_id already dropped from service_line_items")

        # 3. Drop schedule-related index if it survived
        if not is_postgres:
            # SQLite: indexes were recreated above without the schedule one
            pass
        else:
            try:
                conn.execute(text("DROP INDEX IF EXISTS idx_service_line_items_schedule"))
            except Exception:
                pass

        # 4. Drop maintenance_schedule_items table
        if inspect(conn).has_table("maintenance_schedule_items"):
            print("Dropping maintenance_schedule_items table...")
            conn.execute(text("DROP TABLE maintenance_schedule_items"))
            print("  Dropped maintenance_schedule_items")
        else:
            print("  maintenance_schedule_items already dropped")

        # 5. Drop maintenance_templates table (if it exists as a DB table)
        if inspect(conn).has_table("maintenance_templates"):
            print("Dropping maintenance_templates table...")
            conn.execute(text("DROP TABLE maintenance_templates"))
            print("  Dropped maintenance_templates")
        else:
            print("  maintenance_templates table not present (templates are file-based)")

        print("Phase 2 migration complete")


if __name__ == "__main__":
    upgrade()

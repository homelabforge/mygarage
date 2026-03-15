"""Add vehicle archive system.

This migration implements soft-delete functionality for vehicles with archive metadata.
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
    """Add archive columns to vehicles table."""
    if engine is None:
        engine = _get_fallback_engine()

    is_postgres = engine.dialect.name == "postgresql"
    ts_type = "TIMESTAMP" if is_postgres else "DATETIME"

    with engine.begin() as conn:
        inspector = inspect(engine)
        print("Adding vehicle archive system...")

        existing_columns = {col["name"] for col in inspector.get_columns("vehicles")}

        if "archived_at" in existing_columns:
            print("  → Archive columns already exist, skipping migration")
            return

        conn.execute(text(f"ALTER TABLE vehicles ADD COLUMN archived_at {ts_type} DEFAULT NULL"))
        print("  ✓ Added archived_at column")

        conn.execute(
            text("ALTER TABLE vehicles ADD COLUMN archive_reason VARCHAR(50) DEFAULT NULL")
        )
        print("  ✓ Added archive_reason column")

        conn.execute(
            text("ALTER TABLE vehicles ADD COLUMN archive_sale_price NUMERIC(10, 2) DEFAULT NULL")
        )
        print("  ✓ Added archive_sale_price column")

        conn.execute(text("ALTER TABLE vehicles ADD COLUMN archive_sale_date DATE DEFAULT NULL"))
        print("  ✓ Added archive_sale_date column")

        conn.execute(text("ALTER TABLE vehicles ADD COLUMN archive_notes TEXT DEFAULT NULL"))
        print("  ✓ Added archive_notes column")

        conn.execute(text("ALTER TABLE vehicles ADD COLUMN archived_visible BOOLEAN DEFAULT true"))
        print("  ✓ Added archived_visible column")

        conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_vehicles_archived_at ON vehicles(archived_at)")
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_vehicles_user_archived ON vehicles(user_id, archived_at)"
            )
        )
        print("  ✓ Created archive indexes")

        print("\n✓ Vehicle archive migration completed successfully")


def downgrade():
    """Rollback not supported."""
    print("Downgrade not supported for ALTER TABLE ADD COLUMN")


if __name__ == "__main__":
    upgrade()

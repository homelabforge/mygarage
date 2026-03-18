"""Fix service_line_items table schema lost during migration 049.

Migration 049 used CREATE TABLE ... AS SELECT which strips all column constraints,
primary key, autoincrement, foreign keys, and check constraints from the table.
This migration recreates the table with the correct schema while preserving data.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, text


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None):
    """Recreate service_line_items with proper schema (PK, FK, constraints)."""
    if engine is None:
        engine = _get_fallback_engine()

    if engine.dialect.name == "postgresql":
        print("PostgreSQL detected — schema was not affected by migration 049, skipping.")
        return

    with engine.begin() as conn:
        # Check if fix is needed by looking at the CREATE TABLE statement
        result = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE name='service_line_items'")
        )
        row = result.fetchone()
        if row and "PRIMARY KEY" in row[0].upper():
            print("service_line_items already has PRIMARY KEY — skipping fix.")
            return

        print("Recreating service_line_items with correct schema...")

        # Disable FK checks during table swap (vehicle_reminders references this table)
        conn.execute(text("PRAGMA foreign_keys = OFF"))

        # 1. Rename broken table out of the way
        conn.execute(text("ALTER TABLE service_line_items RENAME TO _service_line_items_broken"))

        # 2. Create properly defined table with correct name
        conn.execute(
            text("""
            CREATE TABLE service_line_items (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                visit_id        INTEGER NOT NULL REFERENCES service_visits(id) ON DELETE CASCADE,
                description     VARCHAR(200) NOT NULL,
                category        VARCHAR(30),
                cost            DECIMAL(10,2),
                notes           TEXT,
                is_inspection   BOOLEAN DEFAULT 0,
                inspection_result   VARCHAR(20),
                inspection_severity VARCHAR(10),
                triggered_by_inspection_id INTEGER REFERENCES service_line_items(id),
                created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                CHECK (inspection_result IS NULL OR inspection_result IN ('passed', 'failed', 'needs_attention')),
                CHECK (inspection_severity IS NULL OR inspection_severity IN ('green', 'yellow', 'red'))
            )
        """)
        )

        # 3. Copy existing data preserving IDs
        conn.execute(
            text("""
            INSERT INTO service_line_items
                (id, visit_id, description, category, cost, notes,
                 is_inspection, inspection_result, inspection_severity,
                 triggered_by_inspection_id, created_at)
            SELECT
                id, visit_id, description, category, cost, notes,
                is_inspection, inspection_result, inspection_severity,
                triggered_by_inspection_id, created_at
            FROM _service_line_items_broken
        """)
        )

        # 4. Drop broken table and recreate index
        conn.execute(text("DROP TABLE _service_line_items_broken"))
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_service_line_items_visit "
                "ON service_line_items (visit_id)"
            )
        )

        # 5. Re-enable FK checks and verify integrity
        conn.execute(text("PRAGMA foreign_keys = ON"))
        violations = conn.execute(text("PRAGMA foreign_key_check(service_line_items)")).fetchall()
        if violations:
            print(f"  WARNING: {len(violations)} FK violations found")
        else:
            print("  FK integrity check passed.")

        print("  service_line_items schema restored with PK, FK, and constraints.")


if __name__ == "__main__":
    upgrade()

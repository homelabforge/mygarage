"""Add maintenance_templates table for tracking applied maintenance schedules."""

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
    """Create maintenance_templates table."""
    if engine is None:
        engine = _get_fallback_engine()

    is_postgres = engine.dialect.name == "postgresql"
    pk_type = "SERIAL PRIMARY KEY" if is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts_type = "TIMESTAMP" if is_postgres else "DATETIME"

    with engine.begin() as conn:
        # Check if table already exists
        if inspect(engine).has_table("maintenance_templates"):
            print("✓ maintenance_templates table already exists")
            return

        # Create maintenance_templates table
        print("Creating maintenance_templates table...")
        conn.execute(
            text(f"""
            CREATE TABLE maintenance_templates (
                id {pk_type},
                vin VARCHAR(17) NOT NULL,
                template_source VARCHAR(200) NOT NULL,
                template_version VARCHAR(50),
                template_data JSON NOT NULL,
                applied_at {ts_type} DEFAULT CURRENT_TIMESTAMP,
                created_by VARCHAR(20) DEFAULT 'auto',
                reminders_created INTEGER DEFAULT 0,
                created_at {ts_type} DEFAULT CURRENT_TIMESTAMP,
                updated_at {ts_type},
                FOREIGN KEY (vin) REFERENCES vehicles(vin) ON DELETE CASCADE
            )
        """)
        )

        # Create indexes
        print("Creating indexes on maintenance_templates...")
        conn.execute(
            text("CREATE INDEX idx_maintenance_templates_vin ON maintenance_templates(vin)")
        )
        conn.execute(
            text(
                "CREATE INDEX idx_maintenance_templates_source ON maintenance_templates(template_source)"
            )
        )

        print("✓ Successfully created maintenance_templates table with indexes")


if __name__ == "__main__":
    upgrade()

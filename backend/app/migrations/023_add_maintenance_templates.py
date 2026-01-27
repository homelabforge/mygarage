"""Add maintenance_templates table for tracking applied maintenance schedules."""

import os
from pathlib import Path

from sqlalchemy import create_engine, text


def upgrade():
    """Create maintenance_templates table."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    # Create engine
    engine = create_engine(database_url)

    with engine.begin() as conn:
        # Check if table already exists
        result = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='maintenance_templates'"
            )
        )
        if result.fetchone():
            print("✓ maintenance_templates table already exists")
            return

        # Create maintenance_templates table
        print("Creating maintenance_templates table...")
        conn.execute(
            text("""
            CREATE TABLE maintenance_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vin VARCHAR(17) NOT NULL,
                template_source VARCHAR(200) NOT NULL,
                template_version VARCHAR(50),
                template_data JSON NOT NULL,
                applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                created_by VARCHAR(20) DEFAULT 'auto',
                reminders_created INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME,
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

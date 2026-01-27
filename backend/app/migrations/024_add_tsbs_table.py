"""Add tsbs table for Technical Service Bulletin tracking."""

import os
from pathlib import Path

from sqlalchemy import create_engine, text


def upgrade():
    """Create tsbs table."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    # Create engine
    engine = create_engine(database_url)

    with engine.begin() as conn:
        # Check if table already exists
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='tsbs'")
        )
        if result.fetchone():
            print("✓ tsbs table already exists")
            return

        # Create tsbs table
        print("Creating tsbs table...")
        conn.execute(
            text("""
            CREATE TABLE tsbs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vin VARCHAR(17) NOT NULL,
                tsb_number VARCHAR(50),
                component VARCHAR(200) NOT NULL,
                summary TEXT NOT NULL,
                status VARCHAR(20) DEFAULT 'pending',
                applied_at DATETIME,
                related_service_id INTEGER,
                source VARCHAR(50) DEFAULT 'manual',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME,
                FOREIGN KEY (vin) REFERENCES vehicles(vin) ON DELETE CASCADE,
                FOREIGN KEY (related_service_id) REFERENCES service_records(id) ON DELETE SET NULL
            )
        """)
        )

        # Create indexes
        print("Creating indexes on tsbs...")
        conn.execute(text("CREATE INDEX idx_tsbs_vin ON tsbs(vin)"))
        conn.execute(text("CREATE INDEX idx_tsbs_status ON tsbs(status)"))
        conn.execute(text("CREATE INDEX idx_tsbs_tsb_number ON tsbs(tsb_number)"))

        print("✓ Successfully created tsbs table with indexes")


if __name__ == "__main__":
    upgrade()

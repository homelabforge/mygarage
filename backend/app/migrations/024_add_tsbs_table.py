"""Add tsbs table for Technical Service Bulletin tracking."""

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
    """Create tsbs table."""
    if engine is None:
        engine = _get_fallback_engine()

    is_postgres = engine.dialect.name == "postgresql"
    pk_type = "SERIAL PRIMARY KEY" if is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts_type = "TIMESTAMP" if is_postgres else "DATETIME"

    with engine.begin() as conn:
        # Check if table already exists
        if inspect(engine).has_table("tsbs"):
            print("✓ tsbs table already exists")
            return

        # Create tsbs table
        print("Creating tsbs table...")
        conn.execute(
            text(f"""
            CREATE TABLE tsbs (
                id {pk_type},
                vin VARCHAR(17) NOT NULL,
                tsb_number VARCHAR(50),
                component VARCHAR(200) NOT NULL,
                summary TEXT NOT NULL,
                status VARCHAR(20) DEFAULT 'pending',
                applied_at {ts_type},
                related_service_id INTEGER,
                source VARCHAR(50) DEFAULT 'manual',
                created_at {ts_type} DEFAULT CURRENT_TIMESTAMP,
                updated_at {ts_type},
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

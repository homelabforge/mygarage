"""Add spot_rental_billings table for tracking individual billing entries."""

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
    """Create spot_rental_billings table."""
    if engine is None:
        engine = _get_fallback_engine()

    is_postgres = engine.dialect.name == "postgresql"
    pk_type = "SERIAL PRIMARY KEY" if is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts_type = "TIMESTAMP" if is_postgres else "DATETIME"

    with engine.begin() as conn:
        inspector = inspect(engine)

        if inspector.has_table("spot_rental_billings"):
            print("✓ spot_rental_billings table already exists, skipping migration")
            return

        print("Creating spot_rental_billings table...")

        conn.execute(
            text(f"""
            CREATE TABLE spot_rental_billings (
                id {pk_type},
                spot_rental_id INTEGER NOT NULL,
                billing_date DATE NOT NULL,
                monthly_rate NUMERIC(8, 2),
                electric NUMERIC(8, 2),
                water NUMERIC(8, 2),
                waste NUMERIC(8, 2),
                total NUMERIC(10, 2),
                notes TEXT,
                created_at {ts_type} DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (spot_rental_id) REFERENCES spot_rentals(id) ON DELETE CASCADE
            )
        """)
        )
        print("  ✓ Created spot_rental_billings table")

        conn.execute(
            text(
                "CREATE INDEX idx_spot_rental_billings_rental_id ON spot_rental_billings(spot_rental_id)"
            )
        )
        conn.execute(
            text("CREATE INDEX idx_spot_rental_billings_date ON spot_rental_billings(billing_date)")
        )
        print("  ✓ Created indexes")

        print("\n✓ Spot rental billings migration completed successfully")


def downgrade(engine=None):
    """Rollback migration by dropping the table."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS spot_rental_billings"))
        print("✓ Dropped spot_rental_billings table")


if __name__ == "__main__":
    upgrade()

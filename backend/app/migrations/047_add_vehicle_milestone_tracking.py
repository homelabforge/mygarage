"""Add odometer milestone tracking to vehicles.

Adds last_milestone_notified column to vehicles table to track
the last milestone mileage that triggered a notification.
Prevents duplicate milestone notifications.
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


def upgrade(engine=None) -> None:
    """Add last_milestone_notified to vehicles."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        inspector = inspect(engine)
        columns = [col["name"] for col in inspector.get_columns("vehicles")]

        if "last_milestone_notified" not in columns:
            conn.execute(text("ALTER TABLE vehicles ADD COLUMN last_milestone_notified INTEGER"))
            print("  Added column: vehicles.last_milestone_notified")
        else:
            print("  → Column last_milestone_notified already exists, skipping")

    print("  Migration 047 complete: vehicle milestone tracking column added")


def downgrade() -> None:
    """Downgrade not supported — column retained for safety."""
    print("  Downgrade not supported — column retained for safety")


if __name__ == "__main__":
    upgrade()

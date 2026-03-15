"""Add electric, water, and waste utility columns to spot_rentals table."""

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
    """Add utility columns to spot_rentals if they do not exist."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        inspector = inspect(engine)
        existing_columns = {col["name"] for col in inspector.get_columns("spot_rentals")}

        # Whitelist of allowed columns to prevent SQL injection
        allowed_spot_rental_columns = {"electric", "water", "waste"}

        columns_to_add = [
            col for col in ["electric", "water", "waste"] if col not in existing_columns
        ]

        if columns_to_add:
            print(f"Adding {', '.join(columns_to_add)} column(s) to spot_rentals table...")

            for column in columns_to_add:
                if column not in allowed_spot_rental_columns:
                    raise ValueError(f"Invalid column name: {column}")

                conn.execute(text(f"ALTER TABLE spot_rentals ADD COLUMN {column} NUMERIC(8, 2)"))

            print(f"✓ Successfully added {', '.join(columns_to_add)} to spot_rentals")
        else:
            print("✓ spot_rentals utility columns already exist")


if __name__ == "__main__":
    upgrade()

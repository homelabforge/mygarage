"""Add electric, water, and waste utility columns to spot_rentals table."""

import os
from pathlib import Path
from sqlalchemy import text, create_engine


def upgrade():
    """Add utility columns to spot_rentals if they do not exist."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    # Create engine
    engine = create_engine(database_url)

    with engine.begin() as conn:
        # Check which columns exist via PRAGMA table_info
        result = conn.execute(text("PRAGMA table_info(spot_rentals)"))
        columns = {row[1]: row for row in result}

        # Whitelist of allowed columns to prevent SQL injection
        ALLOWED_SPOT_RENTAL_COLUMNS = {'electric', 'water', 'waste'}

        columns_to_add = []
        if 'electric' not in columns:
            columns_to_add.append('electric')
        if 'water' not in columns:
            columns_to_add.append('water')
        if 'waste' not in columns:
            columns_to_add.append('waste')

        if columns_to_add:
            print(f"Adding {', '.join(columns_to_add)} column(s) to spot_rentals table...")

            for column in columns_to_add:
                # Validate column name against whitelist to prevent SQL injection
                if column not in ALLOWED_SPOT_RENTAL_COLUMNS:
                    raise ValueError(f"Invalid column name: {column}")

                conn.execute(text(f"""
                    ALTER TABLE spot_rentals
                    ADD COLUMN {column} NUMERIC(8, 2)
                """))

            print(f"✓ Successfully added {', '.join(columns_to_add)} to spot_rentals")
        else:
            print("✓ spot_rentals utility columns already exist")


if __name__ == "__main__":
    upgrade()

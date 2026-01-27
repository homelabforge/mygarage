"""Add shop finder fields to address_book and service_records."""

import os
from pathlib import Path

from sqlalchemy import create_engine, text


def upgrade():
    """Add geolocation, ratings, and usage tracking to address book."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    # Create engine
    engine = create_engine(database_url)

    with engine.begin() as conn:
        print("Adding shop finder fields to address_book...")

        # Check if columns already exist
        result = conn.execute(text("PRAGMA table_info(address_book)"))
        existing_columns = {row[1] for row in result}

        # Add new columns to address_book if they don't exist
        if "latitude" not in existing_columns:
            conn.execute(text("ALTER TABLE address_book ADD COLUMN latitude NUMERIC(10,8)"))
            print("  ✓ Added latitude column")

        if "longitude" not in existing_columns:
            conn.execute(text("ALTER TABLE address_book ADD COLUMN longitude NUMERIC(11,8)"))
            print("  ✓ Added longitude column")

        if "source" not in existing_columns:
            conn.execute(
                text("ALTER TABLE address_book ADD COLUMN source VARCHAR(20) DEFAULT 'manual'")
            )
            print("  ✓ Added source column")

        if "external_id" not in existing_columns:
            conn.execute(text("ALTER TABLE address_book ADD COLUMN external_id VARCHAR(100)"))
            print("  ✓ Added external_id column")

        if "rating" not in existing_columns:
            conn.execute(text("ALTER TABLE address_book ADD COLUMN rating NUMERIC(3,2)"))
            print("  ✓ Added rating column (Google rating)")

        if "user_rating" not in existing_columns:
            conn.execute(text("ALTER TABLE address_book ADD COLUMN user_rating INTEGER"))
            print("  ✓ Added user_rating column")

        if "usage_count" not in existing_columns:
            conn.execute(text("ALTER TABLE address_book ADD COLUMN usage_count INTEGER DEFAULT 0"))
            print("  ✓ Added usage_count column")

        if "last_used" not in existing_columns:
            conn.execute(text("ALTER TABLE address_book ADD COLUMN last_used DATETIME"))
            print("  ✓ Added last_used column")

        # Check if address_book_id exists in service_records
        result = conn.execute(text("PRAGMA table_info(service_records)"))
        existing_columns = {row[1] for row in result}

        if "address_book_id" not in existing_columns:
            conn.execute(
                text("""
                ALTER TABLE service_records
                ADD COLUMN address_book_id INTEGER
                REFERENCES address_book(id) ON DELETE SET NULL
                """)
            )
            print("  ✓ Added address_book_id to service_records")

            # Create index on the new foreign key
            conn.execute(
                text(
                    "CREATE INDEX idx_service_records_address_book_id ON service_records(address_book_id)"
                )
            )
            print("  ✓ Created index on address_book_id")

        print("✓ Successfully added shop finder fields")


if __name__ == "__main__":
    upgrade()

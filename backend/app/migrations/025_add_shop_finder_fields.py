"""Add shop finder fields to address_book and service_records."""

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
    """Add geolocation, ratings, and usage tracking to address book."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        print("Adding shop finder fields to address_book...")

        # Check if columns already exist
        inspector = inspect(engine)
        existing_columns = {col["name"] for col in inspector.get_columns("address_book")}

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

        # Check if address_book_id exists in service_records (legacy table)
        inspector = inspect(engine)
        if not inspector.has_table("service_records"):
            print("  service_records table does not exist, skipping address_book_id column")
        else:
            existing_columns = {col["name"] for col in inspector.get_columns("service_records")}

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

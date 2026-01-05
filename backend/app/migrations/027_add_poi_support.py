"""Add POI support to address_book table."""

import os
from pathlib import Path
from sqlalchemy import text, create_engine


def upgrade():
    """Add POI category and metadata fields to address_book."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    # Create engine
    engine = create_engine(database_url)

    with engine.begin() as conn:
        print("Adding POI fields to address_book...")

        # Check if columns already exist
        result = conn.execute(text("PRAGMA table_info(address_book)"))
        existing_columns = {row[1] for row in result}

        # Add poi_category column
        if "poi_category" not in existing_columns:
            conn.execute(
                text("ALTER TABLE address_book ADD COLUMN poi_category VARCHAR(50)")
            )
            print("  ✓ Added poi_category column")

        # Add poi_metadata column
        if "poi_metadata" not in existing_columns:
            conn.execute(text("ALTER TABLE address_book ADD COLUMN poi_metadata TEXT"))
            print("  ✓ Added poi_metadata column")

        # Backfill existing service entries
        print("Backfilling existing service entries...")
        result = conn.execute(
            text("""
                UPDATE address_book
                SET poi_category = 'auto_shop'
                WHERE category = 'service' AND poi_category IS NULL
            """)
        )
        print(f"  ✓ Backfilled {result.rowcount} existing service entries")

        # Create index on poi_category
        print("Creating index on poi_category...")
        conn.execute(
            text("""
                CREATE INDEX IF NOT EXISTS idx_address_book_poi_category
                ON address_book(poi_category)
            """)
        )
        print("  ✓ Created index on poi_category")

        # Add provider configuration settings
        print("Adding provider configuration settings...")

        default_settings = [
            ("map_provider", "osm"),
            ("poi_search_providers", "[]"),
            ("google_maps_api_key", ""),
            ("google_places_api_key", ""),
            ("yelp_api_key", ""),
            ("foursquare_api_key", ""),
            ("geoapify_api_key", ""),
            ("mapbox_api_key", ""),
        ]

        for key, value in default_settings:
            result = conn.execute(
                text("SELECT COUNT(*) FROM settings WHERE key = :key"), {"key": key}
            )
            if result.scalar() == 0:
                conn.execute(
                    text("""
                        INSERT INTO settings (key, value, category, encrypted)
                        VALUES (:key, :value, 'integrations', 0)
                    """),
                    {"key": key, "value": value},
                )
                print(f"  ✓ Added setting: {key}")

        print("✓ Successfully added POI support")


if __name__ == "__main__":
    upgrade()

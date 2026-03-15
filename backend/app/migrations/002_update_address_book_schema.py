"""Migration to update address_book table schema.

Changes:
- Make business_name NOT NULL (required)
- Make name NULL (optional)
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


def upgrade(engine=None):
    """Update address_book table to make business_name required and name optional."""
    if engine is None:
        engine = _get_fallback_engine()

    dialect = engine.dialect.name

    with engine.begin() as conn:
        inspector = inspect(engine)

        if not inspector.has_table("address_book"):
            print("  address_book table does not exist, skipping")
            return

        if dialect == "postgresql":
            # PostgreSQL: can ALTER COLUMN directly
            # Backfill business_name where NULL
            conn.execute(
                text("UPDATE address_book SET business_name = name WHERE business_name IS NULL")
            )
            conn.execute(text("ALTER TABLE address_book ALTER COLUMN business_name SET NOT NULL"))
            conn.execute(text("ALTER TABLE address_book ALTER COLUMN name DROP NOT NULL"))
            # Set name to NULL where it was same as business_name
            conn.execute(text("UPDATE address_book SET name = NULL WHERE name = business_name"))
            print("✓ Successfully updated address_book table schema on PostgreSQL")
        else:
            # SQLite: must rebuild table
            conn.execute(text("DROP TABLE IF EXISTS address_book_new"))

            conn.execute(
                text("""
                CREATE TABLE address_book_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    business_name VARCHAR(150) NOT NULL,
                    name VARCHAR(100),
                    address TEXT,
                    city VARCHAR(100),
                    state VARCHAR(50),
                    zip_code VARCHAR(20),
                    phone VARCHAR(20),
                    email VARCHAR(100),
                    website VARCHAR(200),
                    category VARCHAR(50),
                    notes TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            )

            conn.execute(
                text("""
                INSERT INTO address_book_new (
                    id, business_name, name, address, city, state, zip_code,
                    phone, email, website, category, notes, created_at, updated_at
                )
                SELECT
                    id,
                    COALESCE(business_name, name) as business_name,
                    CASE WHEN business_name IS NOT NULL THEN name ELSE NULL END as name,
                    address, city, state, zip_code,
                    phone, email, website, category, notes, created_at, updated_at
                FROM address_book
            """)
            )

            conn.execute(text("DROP TABLE address_book"))
            conn.execute(text("ALTER TABLE address_book_new RENAME TO address_book"))
            conn.execute(text("CREATE INDEX idx_address_book_name ON address_book(name)"))
            conn.execute(text("CREATE INDEX idx_address_book_category ON address_book(category)"))
            print("✓ Successfully updated address_book table schema on SQLite")


def downgrade(engine=None):
    """Revert address_book table changes."""
    if engine is None:
        engine = _get_fallback_engine()

    dialect = engine.dialect.name

    with engine.begin() as conn:
        if dialect == "postgresql":
            conn.execute(text("UPDATE address_book SET name = business_name WHERE name IS NULL"))
            conn.execute(text("ALTER TABLE address_book ALTER COLUMN name SET NOT NULL"))
            conn.execute(text("ALTER TABLE address_book ALTER COLUMN business_name DROP NOT NULL"))
            print("✓ Successfully reverted address_book table schema on PostgreSQL")
        else:
            conn.execute(text("DROP TABLE IF EXISTS address_book_new"))
            conn.execute(
                text("""
                CREATE TABLE address_book_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(100) NOT NULL,
                    business_name VARCHAR(150),
                    address TEXT,
                    city VARCHAR(100),
                    state VARCHAR(50),
                    zip_code VARCHAR(20),
                    phone VARCHAR(20),
                    email VARCHAR(100),
                    website VARCHAR(200),
                    category VARCHAR(50),
                    notes TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            )
            conn.execute(
                text("""
                INSERT INTO address_book_new (
                    id, name, business_name, address, city, state, zip_code,
                    phone, email, website, category, notes, created_at, updated_at
                )
                SELECT
                    id,
                    COALESCE(name, business_name) as name,
                    business_name,
                    address, city, state, zip_code,
                    phone, email, website, category, notes, created_at, updated_at
                FROM address_book
            """)
            )
            conn.execute(text("DROP TABLE address_book"))
            conn.execute(text("ALTER TABLE address_book_new RENAME TO address_book"))
            conn.execute(text("CREATE INDEX idx_address_book_name ON address_book(name)"))
            conn.execute(text("CREATE INDEX idx_address_book_category ON address_book(category)"))
            print("✓ Successfully reverted address_book table schema on SQLite")


if __name__ == "__main__":
    upgrade()

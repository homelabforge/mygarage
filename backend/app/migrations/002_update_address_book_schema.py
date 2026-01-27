"""Migration to update address_book table schema.

Changes:
- Make business_name NOT NULL (required)
- Make name NULL (optional)
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, text


def upgrade():
    """Update address_book table to make business_name required and name optional."""
    # Create a synchronous engine for migrations
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    sync_engine = create_engine(database_url)

    with sync_engine.begin() as conn:
        # SQLite doesn't support ALTER COLUMN, so we need to recreate the table

        # 1. Create new table with updated schema
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

        # 2. Copy data from old table to new table
        # Set business_name to name if business_name is empty, and name to NULL if it was the same
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

        # 3. Drop old table
        conn.execute(text("DROP TABLE address_book"))

        # 4. Rename new table to old table name
        conn.execute(text("ALTER TABLE address_book_new RENAME TO address_book"))

        # 5. Recreate indexes
        conn.execute(text("CREATE INDEX idx_address_book_name ON address_book(name)"))
        conn.execute(text("CREATE INDEX idx_address_book_category ON address_book(category)"))

        print("✓ Successfully updated address_book table schema")


def downgrade():
    """Revert address_book table changes."""
    # Create a synchronous engine for migrations
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    sync_engine = create_engine(database_url)

    with sync_engine.begin() as conn:
        # Create old table structure
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

        # Copy data back
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

        print("✓ Successfully reverted address_book table schema")


if __name__ == "__main__":
    upgrade()

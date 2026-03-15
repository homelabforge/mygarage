"""Sync existing address book entries to the vendors table.

For every address_book entry that has a business_name, inserts a matching
vendor row if one with that name does not already exist. Uses
INSERT ... ON CONFLICT DO NOTHING for cross-database compatibility.

Uses DISTINCT ON (PostgreSQL) or GROUP BY (SQLite) to deduplicate by
normalized name, picking one representative row per business name.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, text


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None) -> None:
    """Insert address book business names into vendors where not already present."""
    if engine is None:
        engine = _get_fallback_engine()

    is_postgres = engine.dialect.name == "postgresql"

    with engine.begin() as conn:
        if is_postgres:
            # PostgreSQL: use DISTINCT ON for dedup (stricter GROUP BY rules)
            result = conn.execute(
                text("""
                    INSERT INTO vendors (name, address, city, state, zip_code, phone)
                    SELECT DISTINCT ON (LOWER(TRIM(business_name)))
                           TRIM(SUBSTRING(business_name FROM 1 FOR 100)),
                           address, city, state, zip_code, phone
                    FROM address_book
                    WHERE business_name IS NOT NULL AND TRIM(business_name) != ''
                    ON CONFLICT (name) DO NOTHING
                """)
            )
        else:
            # SQLite: GROUP BY picks an arbitrary row per group (acceptable here)
            result = conn.execute(
                text("""
                    INSERT INTO vendors (name, address, city, state, zip_code, phone)
                    SELECT TRIM(SUBSTR(business_name, 1, 100)),
                           address, city, state, zip_code, phone
                    FROM address_book
                    WHERE business_name IS NOT NULL AND TRIM(business_name) != ''
                    GROUP BY LOWER(TRIM(business_name))
                    ON CONFLICT (name) DO NOTHING
                """)
            )

        count = result.rowcount
        if count > 0:
            print(f"  Synced {count} address book entries to vendors table")
        else:
            print("  No new vendors to sync from address book")


def downgrade() -> None:
    """Downgrade not supported — vendor rows created from address book are retained."""
    print("  Downgrade not supported — vendor rows retained for safety")


if __name__ == "__main__":
    upgrade()

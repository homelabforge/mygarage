"""Sync existing address book entries to the vendors table.

For every address_book entry that has a business_name, inserts a matching
vendor row if one with that name does not already exist. Uses INSERT OR IGNORE
because vendors.name has a UNIQUE constraint (SQLite-specific syntax).

Row selection for duplicate business names (by normalized name) is
nondeterministic — SQLite GROUP BY picks an arbitrary row per group.
This is acceptable for a one-time backfill where the important field is
the name itself.

SUBSTR(TRIM(business_name), 1, 100) enforces the vendors.name VARCHAR(100)
limit (address_book.business_name allows 150 chars).
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, text


def upgrade() -> None:
    """Insert address book business names into vendors where not already present."""
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    engine = create_engine(database_url)

    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT OR IGNORE INTO vendors (name, address, city, state, zip_code, phone)
                SELECT TRIM(SUBSTR(business_name, 1, 100)),
                       address, city, state, zip_code, phone
                FROM address_book
                WHERE business_name IS NOT NULL AND TRIM(business_name) != ''
                GROUP BY LOWER(TRIM(business_name))
                """
            )
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

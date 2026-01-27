"""Add tax and fees columns to service_visits table.

This migration adds:
- tax_amount: Sales tax
- shop_supplies: Shop supplies/environmental fees
- misc_fees: Miscellaneous fees (disposal, etc.)

These allow the total cost to match real-world invoices that include
additional charges beyond just parts and labor.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, text


def upgrade():
    """Add tax_amount, shop_supplies, and misc_fees columns to service_visits."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    # Create engine
    engine = create_engine(database_url)

    with engine.begin() as conn:
        # Check if service_visits table exists
        result = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='service_visits'"
            )
        )
        if not result.fetchone():
            print("  service_visits table does not exist, skipping")
            return

        # Check if columns already exist
        result = conn.execute(text("PRAGMA table_info(service_visits)"))
        existing_columns = {row[1] for row in result.fetchall()}

        columns_to_add = [
            ("tax_amount", "DECIMAL(10,2)"),
            ("shop_supplies", "DECIMAL(10,2)"),
            ("misc_fees", "DECIMAL(10,2)"),
        ]

        for col_name, col_type in columns_to_add:
            if col_name in existing_columns:
                print(f"  Column {col_name} already exists, skipping")
            else:
                conn.execute(
                    text(f"ALTER TABLE service_visits ADD COLUMN {col_name} {col_type}")
                )
                print(f"  Added column {col_name}")

        print("  Migration complete")


if __name__ == "__main__":
    upgrade()

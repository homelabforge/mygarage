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

from sqlalchemy import create_engine, inspect, text


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None):
    """Add tax_amount, shop_supplies, and misc_fees columns to service_visits."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        # Check if service_visits table exists
        if not inspect(engine).has_table("service_visits"):
            print("  service_visits table does not exist, skipping")
            return

        # Check if columns already exist
        inspector = inspect(engine)
        existing_columns = {col["name"] for col in inspector.get_columns("service_visits")}

        columns_to_add = [
            ("tax_amount", "DECIMAL(10,2)"),
            ("shop_supplies", "DECIMAL(10,2)"),
            ("misc_fees", "DECIMAL(10,2)"),
        ]

        for col_name, col_type in columns_to_add:
            if col_name in existing_columns:
                print(f"  Column {col_name} already exists, skipping")
            else:
                conn.execute(text(f"ALTER TABLE service_visits ADD COLUMN {col_name} {col_type}"))
                print(f"  Added column {col_name}")

        print("  Migration complete")


if __name__ == "__main__":
    upgrade()

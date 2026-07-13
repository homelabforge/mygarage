"""Add rebate column to fuel records.

A fuel-up may carry a rebate/discount/points redemption that reduces what the
driver actually paid. The stored ``cost`` holds the NET (``price × volume −
rebate``) so every cost analytic that sums ``cost`` reflects real spend without
change; ``rebate`` keeps the redeemed amount for display and round-trip fidelity.

FATAL: the ``FuelRecord`` model maps ``rebate``, so every fuel query selects the
column. A missing column would break all fuel reads. The migration runner
log-and-continues on non-FATAL failure (``database.py``; there is no
``strict_migrations`` enforcement), so halting startup is correct here.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

FATAL = True


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None):
    """Add nullable rebate column to fuel_records (NUMERIC(8,2))."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        inspector = inspect(engine)
        print("Adding fuel rebate support...")

        existing_columns = {col["name"] for col in inspector.get_columns("fuel_records")}

        if "rebate" in existing_columns:
            print("  → rebate column already exists, skipping migration")
            return

        # NUMERIC(8,2) is valid on both SQLite and PostgreSQL. Nullable — a
        # fill-up without a rebate simply leaves it NULL.
        conn.execute(text("ALTER TABLE fuel_records ADD COLUMN rebate NUMERIC(8, 2)"))
        print("  ✓ Added rebate column to fuel_records table")

        print("\n✓ Fuel rebate migration completed successfully")


def downgrade():
    """Rollback not supported."""
    print("Downgrade not supported for ALTER TABLE ADD COLUMN")


if __name__ == "__main__":
    upgrade()

"""Add optional VIN column to external_vehicles for NHTSA lookup storage.

FATAL: ExternalVehicle.vin is on the ORM model; existing deployments need the
column or startup/create flows that expect it will break.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

FATAL = True


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None):
    """Add nullable vin column to external_vehicles if missing."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        inspector = inspect(engine)
        print("Adding external_vehicles.vin support...")

        if "external_vehicles" not in inspector.get_table_names():
            print("  → external_vehicles missing; skip (run 085 first)")
            return

        existing = {col["name"] for col in inspector.get_columns("external_vehicles")}
        if "vin" in existing:
            print("  → vin column already exists, skipping")
            return

        conn.execute(text("ALTER TABLE external_vehicles ADD COLUMN vin VARCHAR(17)"))
        print("  ✓ Added vin column to external_vehicles")
        print("\n✓ External vehicle VIN migration completed successfully")


def downgrade():
    print("Downgrade not supported for ALTER TABLE ADD COLUMN")


if __name__ == "__main__":
    upgrade()

"""Add EV/PHEV charge-session fields onto fuel_records.

Extends the existing kWh fill-up shape with SOC, charger level, location,
and optional battery SOH — charging sessions sit beside gasoline fill-ups
on the same table (fuel_type_used='electric' / kwh set).

FATAL: FuelRecord ORM declares these columns; silent skip would 500 on
read/write once the model is imported.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

FATAL = True

COLUMNS = {
    "soc_start_pct": "NUMERIC(5, 2)",
    "soc_end_pct": "NUMERIC(5, 2)",
    "charge_level": "VARCHAR(10)",
    "charge_location": "VARCHAR(20)",
    "battery_soh_pct": "NUMERIC(5, 2)",
}


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None) -> None:
    if engine is None:
        engine = _get_fallback_engine()

    inspector = inspect(engine)
    if not inspector.has_table("fuel_records"):
        return

    existing = {col["name"] for col in inspector.get_columns("fuel_records")}
    with engine.begin() as conn:
        for name, coltype in COLUMNS.items():
            if name in existing:
                print(f"✓ fuel_records.{name} already exists")
                continue
            conn.execute(text(f"ALTER TABLE fuel_records ADD COLUMN {name} {coltype}"))
            print(f"✓ Added fuel_records.{name}")

    print("✓ Migration 086 (EV charge sessions) completed")


def downgrade() -> None:
    print("Downgrade not supported — restore from backup")


if __name__ == "__main__":
    upgrade()

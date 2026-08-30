"""Add structured maintenance-spec columns on vehicles (oil, torque, fluids).

FATAL: the Vehicle ORM maps these columns; every vehicle SELECT includes them,
so a silent skip would 500 all vehicle reads after the model change.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

FATAL = True

_COLUMNS: tuple[tuple[str, str], ...] = (
    ("oil_viscosity", "VARCHAR(30)"),
    ("oil_capacity_liters", "NUMERIC(5,2)"),
    ("oil_filter_part_number", "VARCHAR(50)"),
    ("lug_nut_torque_nm", "NUMERIC(6,1)"),
    ("coolant_type", "VARCHAR(50)"),
    ("brake_fluid_type", "VARCHAR(30)"),
    ("transmission_fluid_type", "VARCHAR(50)"),
    ("maintenance_specs_notes", "VARCHAR(500)"),
)


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
    if not inspector.has_table("vehicles"):
        return

    existing = {c["name"] for c in inspector.get_columns("vehicles")}
    missing = [(name, ddl) for name, ddl in _COLUMNS if name not in existing]
    if not missing:
        print("✓ vehicles maintenance-spec columns already present")
        return

    with engine.begin() as conn:
        for name, ddl in missing:
            conn.execute(text(f"ALTER TABLE vehicles ADD COLUMN {name} {ddl}"))
            print(f"✓ Added vehicles.{name}")


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 095 is forward-only.")


if __name__ == "__main__":
    upgrade()

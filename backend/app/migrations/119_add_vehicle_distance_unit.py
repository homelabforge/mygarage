"""Add vehicles.distance_unit: the unit the vehicle's odometer reads (#172).

'km', 'mi', or NULL for "Account default", which keeps today's behaviour: the
vehicle's distances show in whoever is viewing's units. No backfill, so every
existing vehicle is NULL and nothing changes on upgrade. Storage stays
metric-canonical; this only decides how a vehicle's distances and speeds are
shown and read.

FATAL: the ORM maps the column and selects it on every vehicle query, so a
silent failure would boot the app against a missing column (the reason 080 and
096 are FATAL too). VARCHAR(2) is identical on SQLite and PostgreSQL.
Idempotent: the column is added only when absent.
"""

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = True


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None):
    """Add vehicles.distance_unit (nullable, no backfill)."""
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()

    if not inspect(engine).has_table("vehicles"):
        return

    with engine.begin() as conn:
        existing = {col["name"] for col in inspect(engine).get_columns("vehicles")}
        if "distance_unit" not in existing:
            conn.execute(text("ALTER TABLE vehicles ADD COLUMN distance_unit VARCHAR(2)"))
            print("  ✓ Added vehicles.distance_unit (nullable)")
        else:
            print("  → distance_unit already exists, skipping")


def downgrade():
    """Rollback not supported."""
    print("Downgrade not supported for ALTER TABLE ADD COLUMN")


if __name__ == "__main__":
    upgrade()

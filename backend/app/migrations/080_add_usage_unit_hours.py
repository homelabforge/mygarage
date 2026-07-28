"""Add per-vehicle usage tracking dimension (usage_unit + current_hours).

Most vehicles are tracked by distance (odometer, km-canonical). Hour-metered
vehicles (utility ATVs, side-by-sides, equipment) are tracked by engine hours
instead. This adds a per-vehicle ``usage_unit`` ('distance' | 'hours', default
'distance') and a ``current_hours`` reading used when a vehicle tracks hours.
Display-only relabel for now — the distance-based analytics (fuel economy,
mileage service intervals, odometer milestones) stay distance-oriented and are
hidden for hour vehicles; a full hours model is a later feature.

FATAL: the ``Vehicle`` model declares ``usage_unit`` as a non-nullable column and
serializes it on every vehicle read. The migration runner log-and-continues on
non-FATAL failure (``database.py``; no ``strict_migrations`` enforcement), so a
silent failure would boot the app against a missing column. ``current_hours`` is
nullable and needs no backfill. VARCHAR/NUMERIC are valid on both SQLite and
PostgreSQL, so no dialect-specific type rewrite is needed. Idempotent.
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
    """Add usage_unit (default 'distance') and current_hours (nullable) to vehicles."""
    if engine is None:
        engine = _get_fallback_engine()

    if not inspect(engine).has_table("vehicles"):
        return

    with engine.begin() as conn:
        existing = {col["name"] for col in inspect(engine).get_columns("vehicles")}

        if "usage_unit" not in existing:
            conn.execute(
                text("ALTER TABLE vehicles ADD COLUMN usage_unit VARCHAR(10) DEFAULT 'distance'")
            )
            result = conn.execute(
                text("UPDATE vehicles SET usage_unit = 'distance' WHERE usage_unit IS NULL")
            )
            print(
                f"  ✓ Added vehicles.usage_unit (backfilled {result.rowcount} row(s) to 'distance')"
            )
        else:
            print("  → usage_unit already exists, skipping")

        if "current_hours" not in existing:
            conn.execute(text("ALTER TABLE vehicles ADD COLUMN current_hours NUMERIC(10, 1)"))
            print("  ✓ Added vehicles.current_hours (nullable)")
        else:
            print("  → current_hours already exists, skipping")

    print("\n✓ Usage-unit migration completed successfully")


def downgrade():
    """Rollback not supported."""
    print("Downgrade not supported for ALTER TABLE ADD COLUMN")


if __name__ == "__main__":
    upgrade()

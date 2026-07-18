"""Add vehicles.location_tracking_enabled (default on) for #118 GPS opt-out.

FATAL: the Vehicle model maps this column; every vehicle SELECT includes it, so
a silent skip would 500 all vehicle reads.
"""

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
    if engine is None:
        engine = _get_fallback_engine()
    inspector = inspect(engine)
    if not inspector.has_table("vehicles"):
        return
    if "location_tracking_enabled" in {c["name"] for c in inspector.get_columns("vehicles")}:
        return
    is_pg = engine.dialect.name == "postgresql"
    default_literal = "TRUE" if is_pg else "1"
    with engine.begin() as conn:
        conn.execute(
            text(
                f"ALTER TABLE vehicles ADD COLUMN location_tracking_enabled BOOLEAN NOT NULL DEFAULT {default_literal}"
            )
        )
        # Backfill safety (some SQLite paths leave NULL when adding NOT NULL DEFAULT to an existing table)
        conn.execute(
            text(
                f"UPDATE vehicles SET location_tracking_enabled = {default_literal} WHERE location_tracking_enabled IS NULL"
            )
        )


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 075 is forward-only.")


if __name__ == "__main__":
    upgrade()

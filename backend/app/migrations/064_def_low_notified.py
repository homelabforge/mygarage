"""Add ``vehicles.def_low_notified_at`` for DEF-low crossing dedup.

Task 14 (dispatcher event) added a `def_low` notification event that fires
whenever DEF level drops below the configured threshold. Without a dedup
marker, every telemetry frame or check cycle while the tank stays below
threshold would re-dispatch a fresh notification. Task 16 will add the
daily scheduled check that stamps this column with the current UTC time
when a low-DEF notification is sent, and clears it once the level recovers
above the threshold — giving crossing-based (not time-based) dedup.

Idempotent (column-exists guard before ADD COLUMN), dialect-aware (SQLite +
PostgreSQL — ``DATETIME`` is translated to ``TIMESTAMP`` for PG, mirroring
migration 054's ``_PG_TYPE_REWRITES`` pattern), forward-only.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

_COLUMN_TYPE_SQLITE = "DATETIME"
_COLUMN_TYPE_PG = "TIMESTAMP"


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def _column_exists(inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade(engine=None) -> None:
    """Add the nullable `def_low_notified_at` dedup column."""
    if engine is None:
        engine = _get_fallback_engine()

    print("Migration 064: add vehicles.def_low_notified_at...")

    inspector = inspect(engine)
    if not inspector.has_table("vehicles"):
        print("  = vehicles table absent, skipping")
        print("Migration 064 complete.")
        return

    if _column_exists(inspector, "vehicles", "def_low_notified_at"):
        print("  = def_low_notified_at already present, skipping")
        print("Migration 064 complete.")
        return

    column_type = _COLUMN_TYPE_PG if engine.dialect.name == "postgresql" else _COLUMN_TYPE_SQLITE
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE vehicles ADD COLUMN def_low_notified_at {column_type}"))
    print("  + Added vehicles.def_low_notified_at (nullable)")
    print("Migration 064 complete.")


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError(
        "Migration 064 is forward-only. It only adds a nullable column with "
        "no prior state; there is nothing meaningful to restore."
    )


if __name__ == "__main__":
    upgrade()

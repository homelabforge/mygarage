"""Add the hour meter beside the odometer on tire mounts and readings (#217).

An hours-only vehicle had nowhere to put a tire's hours, so the hour meter
went into the odometer fields and became hidden odometer rows. Nullable, no
backfill: those old figures can't be told from real odometers.

FATAL for migration 100's reason: the ORM maps all three columns, so every
tire SELECT names them and a silent skip would 500 every tire read.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = True

logger = logging.getLogger(__name__)

#: (table, column, DDL). NUMERIC(10, 1) is the `hours_records.engine_hours` type.
_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("tire_mount_periods", "mounted_hours", "NUMERIC(10, 1)"),
    ("tire_mount_periods", "dismounted_hours", "NUMERIC(10, 1)"),
    ("tire_readings", "engine_hours", "NUMERIC(10, 1)"),
)


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Add the hour columns to tire mount periods and readings where missing."""
    if engine is None:
        engine = _get_fallback_engine()

    inspector = inspect(engine)
    missing: list[tuple[str, str, str]] = []
    for table, name, ddl in _COLUMNS:
        if not inspector.has_table(table):
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        if name not in existing:
            missing.append((table, name, ddl))
    if not missing:
        logger.info("tire hour columns already present")
        return

    with engine.begin() as conn:
        for table, name, ddl in missing:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
            logger.info("Added %s.%s", table, name)


def downgrade() -> None:  # pragma: no cover
    """Rollback not supported."""
    raise NotImplementedError("Migration 126 is forward-only.")


if __name__ == "__main__":
    upgrade()

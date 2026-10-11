"""Drop vehicle_reminders.projected_distance_km, a column nothing writes or reads.

097 added it for the distance a low-tread reminder projected the tire had
left. The low-tread change stopped writing it, and nothing ever read it.

Non-FATAL: a failed run leaves a nullable column no model maps and nothing
reads.

SQLite takes the DROP COLUMN as is (3.35+) because no CHECK, index or FK names
the column, the same rule 089 relies on. If one ever does, SQLite refuses
instead of dropping it.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = False

logger = logging.getLogger(__name__)


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Drop the column if it's still there."""
    if engine is None:
        engine = _get_fallback_engine()

    inspector = inspect(engine)
    if not inspector.has_table("vehicle_reminders"):
        return
    columns = {c["name"] for c in inspector.get_columns("vehicle_reminders")}
    if "projected_distance_km" not in columns:
        return

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE vehicle_reminders DROP COLUMN projected_distance_km"))
    logger.info("Dropped vehicle_reminders.projected_distance_km")


def downgrade() -> None:  # pragma: no cover
    """Rollback not supported."""
    raise NotImplementedError("Migration 128 is forward-only.")


if __name__ == "__main__":
    upgrade()

"""Clear a fill-up's driver when it names a user that no longer exists (B3-1).

054 added ``fuel_records.driver_user_id`` on SQLite with no FK, so deleting a
user there left their id on every fill-up they drove. The fuel API refuses a
driver who isn't a user now, and the user delete clears it, so this clears the
ones already stored, the way ON DELETE SET NULL would have. On PostgreSQL the
FK has kept them clean, so it finds nothing there.

Not FATAL: if it fails, the dead ids stay, which is today, and an edit that
leaves the driver alone still saves.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    # hide_parameters: a failed statement's message leaves out its bound values.
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}", hide_parameters=True)
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}", hide_parameters=True)


def _clear_dangling_drivers(engine: Engine) -> None:
    """NULL every driver_user_id with no users row behind it."""
    inspector = inspect(engine)
    if not (inspector.has_table("fuel_records") and inspector.has_table("users")):
        logger.info("138: fuel_records or users missing; nothing to clear")
        return
    if "driver_user_id" not in {c["name"] for c in inspector.get_columns("fuel_records")}:
        logger.info("138: fuel_records.driver_user_id missing; nothing to clear")
        return
    with engine.begin() as conn:
        cleared = conn.execute(
            text(
                "UPDATE fuel_records SET driver_user_id = NULL"
                " WHERE driver_user_id IS NOT NULL"
                " AND NOT EXISTS (SELECT 1 FROM users WHERE users.id = fuel_records.driver_user_id)"
            )
        ).rowcount
    logger.info("138: cleared %d fill-up driver(s) naming a deleted user", cleared)


def upgrade(engine: Engine | None = None) -> None:
    """Clear the dead driver ids. A failure is logged so the migrations after it still run."""
    if engine is None:
        engine = _get_fallback_engine()
    try:
        _clear_dangling_drivers(engine)
    except SQLAlchemyError as e:
        logger.error("138: dead fill-up drivers not cleared, they stay: %s", e, exc_info=True)


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError("Migration 138 is forward-only.")


if __name__ == "__main__":
    upgrade()

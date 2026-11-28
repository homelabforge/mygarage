"""Add supplies.volume_unit, the per-supply display unit token (#191).

A nullable VARCHAR(8) holding the unit a volume supply is shown in (a token like
'qt_us' or 'mL'). NULL means the legacy binary pick, so every existing supply
behaves exactly as before. No backfill and no CHECK: reads are lenient, so an
unknown token comes out as NULL, and a CHECK would need a SQLite rebuild for
nothing.

FATAL: the model declares the column and every supply query selects it, so a
silent failure would boot the app against a missing column (093's precedent).
Idempotent: the column is added only when absent. A VARCHAR is identical on
SQLite and PostgreSQL, so there is no per-dialect type.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

logger = logging.getLogger(__name__)

FATAL = True


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Add supplies.volume_unit (nullable VARCHAR(8), no backfill)."""
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()

    if not inspect(engine).has_table("supplies"):
        return

    with engine.begin() as conn:
        existing = {col["name"] for col in inspect(engine).get_columns("supplies")}
        if "volume_unit" not in existing:
            conn.execute(text("ALTER TABLE supplies ADD COLUMN volume_unit VARCHAR(8)"))
            logger.info("124: added supplies.volume_unit (nullable)")
        else:
            logger.info("124: supplies.volume_unit already there")


def downgrade() -> None:
    """Rollback not supported."""
    logger.info("124: downgrade not supported for ALTER TABLE ADD COLUMN")


if __name__ == "__main__":
    upgrade()

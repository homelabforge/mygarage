"""Add supply_usages.cost_estimated: a usage priced from the all-time average (#307).

A visit usage is priced at its supply's average over costed purchases dated
on or before the visit. With none there, it takes the all-time average and
this flag is set, so the app can settle it once an on/before purchase shows up.
NOT NULL, default false: every usage priced so far keeps its price, unflagged.

Column only; 163 prices the stranded visit usages. FATAL: the model maps it
NOT NULL and every usage SELECT reads it. Idempotent: added only when absent.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

logger = logging.getLogger(__name__)

FATAL = True

_TABLE = "supply_usages"
_COLUMN = "cost_estimated"


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    # hide_parameters: a failed statement's message leaves out its bound values.
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}", hide_parameters=True)
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}", hide_parameters=True)


def upgrade(engine: Engine | None = None) -> None:
    """Add supply_usages.cost_estimated, NOT NULL DEFAULT false."""
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()

    inspector = inspect(engine)
    if not inspector.has_table(_TABLE):
        logger.info("162: %s missing; nothing to add", _TABLE)
        return
    if _COLUMN in {c["name"] for c in inspector.get_columns(_TABLE)}:
        logger.info("162: %s.%s already there", _TABLE, _COLUMN)
        return

    # The literal the model's false() renders on each dialect, so the default
    # reflects the same as create_all's.
    false = "FALSE" if engine.dialect.name == "postgresql" else "0"
    with engine.begin() as conn:
        conn.execute(
            text(f"ALTER TABLE {_TABLE} ADD COLUMN {_COLUMN} BOOLEAN NOT NULL DEFAULT {false}")
        )
    logger.info("162: added %s.%s", _TABLE, _COLUMN)


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError("Migration 162 is forward-only.")


if __name__ == "__main__":
    upgrade()

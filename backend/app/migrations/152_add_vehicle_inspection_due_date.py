"""Add vehicles.inspection_due_date, the deadline field X.1 prints (#211).

Field X.1 of an EU registration certificate (« VISITE AVANT LE » on a
French carte grise) is the date the NEXT periodic inspection is due by, not
the date of one that was passed. The import keeps it here and the inspection
engine makes its reminder due no later than it while no inspection is on
record; it is never turned into service history.

A nullable DATE, no backfill: the fork's import recorded X.1 as a passed
inspection visit, and those visits are a person's to keep or delete.

FATAL: the model declares the column and every vehicle query selects it, so
a silent failure would boot the app against a missing column (147's
precedent). Idempotent: the column is added only when absent. DATE is the
same type on SQLite and PostgreSQL.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = True

_TABLE = "vehicles"
_COLUMN = "inspection_due_date"


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Add vehicles.inspection_due_date (nullable DATE, no backfill)."""
    if engine is None:
        engine = _get_fallback_engine()
    if not inspect(engine).has_table(_TABLE):
        return
    with engine.begin() as conn:
        existing = {col["name"] for col in inspect(engine).get_columns(_TABLE)}
        if _COLUMN in existing:
            return
        conn.execute(text(f"ALTER TABLE {_TABLE} ADD COLUMN {_COLUMN} DATE"))


if __name__ == "__main__":
    upgrade()

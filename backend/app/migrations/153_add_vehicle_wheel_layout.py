"""Add vehicles.wheel_layout, the per-vehicle wheel layout override (#272).

NULL means "whatever the type usually has" (`default_wheel_layout`), so a
nullable VARCHAR(20) with no backfill: every existing vehicle reads as its
type's default until someone picks a layout.

FATAL: the model declares the column and every vehicle query selects it, so
a silent failure would boot the app against a missing column (147's
precedent). Idempotent: the column is added only when absent. VARCHAR(20) is
the same type on SQLite and PostgreSQL.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = True

_TABLE = "vehicles"
_COLUMN = "wheel_layout"


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Add vehicles.wheel_layout (nullable VARCHAR(20), no backfill)."""
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()
    if not inspect(engine).has_table(_TABLE):
        return
    with engine.begin() as conn:
        existing = {col["name"] for col in inspect(engine).get_columns(_TABLE)}
        if _COLUMN in existing:
            return
        conn.execute(text(f"ALTER TABLE {_TABLE} ADD COLUMN {_COLUMN} VARCHAR(20)"))


if __name__ == "__main__":
    upgrade()

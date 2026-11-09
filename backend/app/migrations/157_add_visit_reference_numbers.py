"""Add invoice, PO and work order numbers to service_visits.

Three nullable VARCHAR(50) columns beside insurance_claim_number, no default
and no backfill: an old visit just has none of them.

FATAL: the model maps all three and every visit query selects them, so a
silent failure would boot the app against missing columns (152's precedent).
Idempotent: each column is added only when absent. A nullable VARCHAR(50) is
the same ADD COLUMN on SQLite and PostgreSQL.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = True

_TABLE = "service_visits"
_COLUMNS = ("invoice_number", "po_number", "work_order_number")


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Add service_visits.invoice_number, po_number and work_order_number."""
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
        for column in _COLUMNS:
            if column in existing:
                continue
            conn.execute(text(f"ALTER TABLE {_TABLE} ADD COLUMN {column} VARCHAR(50)"))
            print(f"  ✓ Added {_TABLE}.{column}")


if __name__ == "__main__":
    upgrade()

"""Drop the retired maintenance_templates table.

The DB-backed applied-maintenance-templates feature was retired in stages:
migration 049 dropped the table (Phase 2 of the service-visit overhaul), the
v2.31.0 audit made POST /apply return 410 Gone, and this change removes the
model/service/schema/router. On installs where 049 already ran, the table has
been a create_all-resurrected empty zombie (0 rows). Drop it for good.

Guarded (mirrors 060): drop only if present AND empty; a populated table is
preserved and logged. Idempotent, dialect-aware, forward-only, NON-FATAL.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

TABLE = "maintenance_templates"


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None) -> None:
    """Drop the retired maintenance_templates table if empty."""
    if engine is None:
        engine = _get_fallback_engine()
    is_postgres = engine.dialect.name == "postgresql"
    print(f"Migration 069: drop retired {TABLE} table...")
    if not inspect(engine).has_table(TABLE):
        print(f"  = {TABLE} absent, skipping")
        return
    with engine.begin() as conn:
        if is_postgres:
            conn.execute(text(f'LOCK TABLE "{TABLE}" IN ACCESS EXCLUSIVE MODE'))
        row_count = conn.execute(text(f'SELECT COUNT(*) FROM "{TABLE}"')).scalar() or 0
        if row_count:
            # Deliberate preservation (guard), not a swallowed error: never drop data.
            print(
                f"  ! {TABLE} has {row_count} row(s) — preserving (NOT dropping); investigate + drop manually if intended"
            )
            return
        conn.execute(text(f'DROP TABLE "{TABLE}"'))
        print(f"  - dropped {TABLE}")
    print("Migration 069 complete.")
    # NOTE (R1-H2): no broad try/except here — an actual DROP/connection error must
    # raise so the runner leaves 069 unstamped and retries it, rather than stamping
    # unresolved drift. The has_table/row_count guards keep normal runs from raising.


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError("Migration 069 is forward-only.")


if __name__ == "__main__":
    upgrade()

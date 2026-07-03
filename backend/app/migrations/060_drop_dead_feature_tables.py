"""Drop dead feature tables: tsbs and vincario_*.

Why now: v2.30.1 enables SQLite FK enforcement (PRAGMA foreign_keys=ON).
On HISTORICAL deployments the ``tsbs`` table declares
``related_service_id REFERENCES service_records(...)`` — a parent table
dropped by migration 040 — and with enforcement on, SQLite raises
"foreign key mismatch" on any future DML against a child table whose
parent is missing. (Migration 024 was later amended to reference
``service_visits``, so FRESH installs carry a valid FK; the dead
reference only exists on databases migrated before that amendment.)
Either way, no application code reads or writes tsbs or the vincario_*
tables — both features were removed — so the tables are dropped when
empty regardless of which FK variant they carry.

Deliberately NOT dropped: the ``*_backup*`` tables (operator safety
copies) — those are data, not schema cruft.

Idempotent, dialect-aware (PostgreSQL + SQLite). Guarded: refuses to
drop any table that still contains rows.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

DEAD_TABLES = (
    "tsbs",
    "vincario_cache",
    "vincario_credits",
    "vincario_usage_log",
)


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None) -> None:
    """Drop empty dead-feature tables (tsbs, vincario_*)."""
    if engine is None:
        engine = _get_fallback_engine()

    inspector = inspect(engine)
    print("Migration 060: drop dead feature tables (tsbs, vincario_*)...")

    for table in DEAD_TABLES:
        if not inspector.has_table(table):
            print(f"  = {table} absent, skipping")
            continue

        with engine.begin() as conn:
            row_count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
            if row_count:
                # Fail-safe: a populated table means the feature saw real use
                # somewhere. Keep the data; the dead-FK hazard only bites on
                # writes, and we'd rather surface this loudly than drop rows.
                print(f"  ! {table} has {row_count} row(s) — NOT dropping; investigate manually")
                continue

            conn.execute(text(f"DROP TABLE {table}"))
            print(f"  - dropped {table}")

    print("Migration 060 complete.")


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError(
        "Migration 060 is forward-only. The dropped tables were empty; "
        "recreate from migrations 024/026-era DDL if a dead feature returns."
    )


if __name__ == "__main__":
    upgrade()

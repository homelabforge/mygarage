"""Drop orphaned backup tables left by earlier restructures.

Three legacy ``*_backup`` tables linger on historical databases and serve no
purpose on a fully-migrated schema:

  - ``service_records_backup_20251229`` — a safety copy made by migration 022
    when the service-type schema was redesigned. Its parent ``service_records``
    was later dropped by migration 040, so the backup is orphaned.
  - ``collision_records_backup`` / ``upgrade_records_backup`` — pre-existing
    operator safety copies of since-removed features (named in migration 053,
    never created by a current migration).

Each is dropped **only when empty** — mirroring migration 060's fail-safe: a
populated backup means the operator (or an external install) still holds real
data there, so we preserve it and log loudly rather than discard rows.
Operators who have verified their populated backup is redundant can drop it
manually.

Idempotent, dialect-aware (SQLite + PostgreSQL), forward-only. NON-FATAL: a
cleanup failure must never block application startup.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

ORPHAN_BACKUP_TABLES = (
    "service_records_backup_20251229",
    "collision_records_backup",
    "upgrade_records_backup",
)


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None) -> None:
    """Drop empty orphaned backup tables."""
    if engine is None:
        engine = _get_fallback_engine()

    is_postgres = engine.dialect.name == "postgresql"
    print("Migration 068: drop orphaned backup tables...")

    for table in ORPHAN_BACKUP_TABLES:
        # EVERYTHING for this table — reflection (`inspect`/`has_table`) included —
        # sits inside the failure boundary. A cleanup error of ANY kind (a
        # reflection/connection error, a lock timeout, the count, the drop) must
        # NEVER escape: the runner halts the pending-migration chain on any
        # exception, and because this migration is NON-FATAL the app would then
        # boot against a schema missing every LATER migration. Log and move on;
        # the orphan table simply lingers (harmless — it was already lingering).
        try:
            if not inspect(engine).has_table(table):
                print(f"  = {table} absent, skipping")
                continue
            with engine.begin() as conn:
                # PG: take an exclusive lock spanning the emptiness check and the
                # DROP so a concurrent writer can't insert a row in between. These
                # are orphan tables with no application writers and migrations run
                # single-threaded at startup, so this is belt-and-suspenders — but
                # it makes the empty-only guarantee airtight. SQLite serializes
                # writers at the database level, so no table lock is needed.
                if is_postgres:
                    conn.execute(text(f'LOCK TABLE "{table}" IN ACCESS EXCLUSIVE MODE'))
                row_count = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar() or 0
                if row_count:
                    print(
                        f"  ! {table} has {row_count} row(s) — NOT dropping; "
                        "verify the data is redundant and drop manually if desired"
                    )
                    continue
                conn.execute(text(f'DROP TABLE "{table}"'))
                print(f"  - dropped {table}")
        except Exception as exc:  # cleanup must not abort the chain
            print(f"  ! {table}: cleanup failed ({exc!r}) — leaving table in place")

    print("Migration 068 complete.")


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError(
        "Migration 068 is forward-only. The dropped tables were empty orphans; "
        "there is nothing to restore."
    )


if __name__ == "__main__":
    upgrade()

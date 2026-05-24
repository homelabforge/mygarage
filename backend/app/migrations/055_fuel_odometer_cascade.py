"""Fuel→odometer cascade — issue #69 (Phase 2.5 of v2.27.0-rc2).

When a user creates a fuel record the app auto-syncs an
``odometer_records`` row so the mileage timeline includes the reading.
rc1 marked the link with a free-text note (``[AUTO-SYNC from fuel #N]``)
and set ``odometer_records.source='fuel'`` — but there was no FK. So
deleting a fuel record left an orphan synced odometer entry visible on
the mileage page with nothing backing it.

This migration installs the proper relationship:

1. Add nullable column ``odometer_records.fuel_record_id``.
2. Backfill: parse the existing ``notes`` marker on rows where
   ``source='fuel'`` and set ``fuel_record_id`` where the referenced
   fuel record still exists.
3. Delete orphans: rows whose marker references a fuel record that no
   longer exists. Logged to a side-log so users can audit the cleanup.
4. Add an index on the new column.
5. PG-only: add the FK with ``ON DELETE CASCADE`` so future fuel
   deletions cascade through the database engine. SQLite falls back
   to service-layer cleanup (still better than rc1).

The migration is idempotent — every step is gated on
column/index/constraint existence checks. Re-running is a no-op.

Not marked ``FATAL``: a partial apply is recoverable. The worst case
(column added, FK install fails) leaves us slightly better off than
rc1 — orphans get marked but not strictly enforced — and the next
run picks up where it left off.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

logger = logging.getLogger(__name__)


# Regex matches the existing AUTO-SYNC marker written by
# app/utils/odometer_sync.py: "[AUTO-SYNC from fuel #N]". Used to
# extract the source fuel_record id during backfill.
_AUTO_SYNC_FUEL_PATTERN = re.compile(r"\[AUTO-SYNC from fuel #(\d+)\]")


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def _column_exists(inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def _index_exists(inspector, table: str, index_name: str) -> bool:
    return index_name in {idx["name"] for idx in inspector.get_indexes(table)}


def _pg_fk_exists(conn, name: str, table: str) -> bool:
    return bool(
        conn.execute(
            text(
                "SELECT 1 FROM information_schema.table_constraints "
                "WHERE constraint_name = :name AND table_name = :table "
                "AND constraint_type = 'FOREIGN KEY'"
            ),
            {"name": name, "table": table},
        ).scalar()
    )


def upgrade(engine=None) -> None:
    if engine is None:
        engine = _get_fallback_engine()

    is_postgres = engine.dialect.name == "postgresql"
    inspector = inspect(engine)

    print("Fuel→odometer cascade migration...")

    # --- 1. Add nullable fuel_record_id column ---------------------------
    if _column_exists(inspector, "odometer_records", "fuel_record_id"):
        print("  → fuel_record_id column already present, skipping ADD COLUMN")
    else:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE odometer_records ADD COLUMN fuel_record_id INTEGER"))
        print("  ✓ Added odometer_records.fuel_record_id (nullable)")
        inspector = inspect(engine)

    # --- 2. Backfill: parse [AUTO-SYNC from fuel #N] markers -------------
    # Scope to source='fuel' rows that don't already have fuel_record_id
    # set; that keeps re-runs cheap and avoids rewriting rows we've
    # already linked.
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT id, notes FROM odometer_records "
                "WHERE source = 'fuel' AND fuel_record_id IS NULL"
            )
        ).fetchall()

        backfilled = 0
        unparseable = 0
        orphan_ids: list[int] = []

        # Snapshot the set of existing fuel record ids once so the
        # orphan-detection step is O(1) per row.
        existing_fuel_ids = {
            row[0] for row in conn.execute(text("SELECT id FROM fuel_records")).fetchall()
        }

        for odo_id, notes in rows:
            if not notes:
                unparseable += 1
                continue
            match = _AUTO_SYNC_FUEL_PATTERN.search(notes)
            if not match:
                unparseable += 1
                continue
            fuel_id = int(match.group(1))
            if fuel_id in existing_fuel_ids:
                conn.execute(
                    text("UPDATE odometer_records SET fuel_record_id = :fid WHERE id = :oid"),
                    {"fid": fuel_id, "oid": odo_id},
                )
                backfilled += 1
            else:
                orphan_ids.append(odo_id)

        print(
            f"  → Backfill: {backfilled} linked, {unparseable} unparseable, "
            f"{len(orphan_ids)} orphan(s) detected"
        )

        # --- 3. Delete orphans (referenced fuel record no longer exists) -
        if orphan_ids:
            log_path = os.environ.get("MIGRATION_055_LOG")
            if log_path:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(
                        f"Migration 055 deleted {len(orphan_ids)} orphan synced "
                        f"odometer rows: {orphan_ids}\n"
                    )
            conn.execute(
                text("DELETE FROM odometer_records WHERE id = ANY(:ids)")
                if is_postgres
                else text(
                    "DELETE FROM odometer_records WHERE id IN ("
                    + ",".join(str(i) for i in orphan_ids)
                    + ")"
                ),
                {"ids": orphan_ids} if is_postgres else {},
            )
            print(f"  ✓ Cleaned up {len(orphan_ids)} orphan synced odometer row(s)")

    # --- 4. Index on fuel_record_id --------------------------------------
    inspector = inspect(engine)
    index_name = "idx_odometer_fuel_record_id"
    if _index_exists(inspector, "odometer_records", index_name):
        print(f"  → Index {index_name} already present, skipping")
    else:
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {index_name} ON odometer_records (fuel_record_id)"
                )
            )
        print(f"  ✓ Created index {index_name}")

    # --- 5. PG-only: install ON DELETE CASCADE FK ------------------------
    # SQLite doesn't support ALTER TABLE ADD CONSTRAINT; rely on
    # SQLAlchemy model + service-layer cleanup there. PG enforces the
    # cascade at the engine level — that's the point of this migration.
    if is_postgres:
        with engine.begin() as conn:
            fk_name = "fk_odometer_records_fuel_record"
            if _pg_fk_exists(conn, fk_name, "odometer_records"):
                print(f"  → FK {fk_name} already present, skipping")
            else:
                conn.execute(
                    text(
                        f"ALTER TABLE odometer_records ADD CONSTRAINT {fk_name} "
                        "FOREIGN KEY (fuel_record_id) REFERENCES fuel_records(id) "
                        "ON DELETE CASCADE"
                    )
                )
                print(f"  ✓ Added FK {fk_name} (ON DELETE CASCADE)")

    print("✓ Migration 055 complete")


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError(
        "Migration 055 is forward-only. Restore from a pre-055 backup if needed."
    )

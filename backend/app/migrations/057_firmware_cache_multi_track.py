"""Add ``livelink_firmware_cache.track`` for per-track (OBD vs PRO) caching.

The firmware cache was a single row (``id == 1``) holding one "latest"
version, which cannot represent the two independent WiCAN firmware tracks
(OBD/USB bare tags vs PRO ``p``-suffixed tags). This migration adds a
nullable ``track`` column, clears the stale singleton (the cache is a
daily-refreshed throwaway — the next scheduled check, or the first
``POST /firmware/check``, repopulates one row per track), and adds a unique
index on ``track``.

Idempotent and dialect-aware (PostgreSQL + SQLite). Column and index
existence are checked before each step; the DELETE runs before the unique
index is created so the ambiguous existing row never violates it.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

logger = logging.getLogger(__name__)


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def _column_exists(inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def _index_exists(inspector, table: str, index: str) -> bool:
    return index in {i["name"] for i in inspector.get_indexes(table)}


def upgrade(engine=None) -> None:
    if engine is None:
        engine = _get_fallback_engine()

    inspector = inspect(engine)

    print("Firmware cache multi-track migration...")

    if not inspector.has_table("livelink_firmware_cache"):
        print("  → livelink_firmware_cache table not present yet, nothing to do")
        return

    # 1. Add nullable track column if missing.
    if _column_exists(inspector, "livelink_firmware_cache", "track"):
        print("  → track column already present, skipping add")
    else:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE livelink_firmware_cache ADD COLUMN track VARCHAR(10)"))
        print("  ✓ Added livelink_firmware_cache.track (nullable)")

    # 2. Clear stale singleton rows so the unique index cannot conflict and the
    #    next firmware check repopulates per-track rows. Safe: cache is throwaway.
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM livelink_firmware_cache"))
    print("  ✓ Cleared stale firmware cache rows")

    # 3. Create the unique index on track if missing (re-inspect after the add).
    inspector = inspect(engine)
    if _index_exists(inspector, "livelink_firmware_cache", "ix_livelink_firmware_cache_track"):
        print("  → ix_livelink_firmware_cache_track already present, skipping")
    else:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX ix_livelink_firmware_cache_track "
                    "ON livelink_firmware_cache (track)"
                )
            )
        print("  ✓ Created unique index ix_livelink_firmware_cache_track")

    print("✓ Migration 057 complete")


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError(
        "Migration 057 is forward-only. Restore from a pre-057 backup if needed."
    )

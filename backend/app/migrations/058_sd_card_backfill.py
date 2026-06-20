"""Add SD-card backfill: device_address/sd_backfill_enabled + sd_log_ingest_state.

Idempotent, dialect-aware (PostgreSQL + SQLite).
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


def upgrade(engine=None) -> None:
    """Add device_address/sd_backfill_enabled columns and sd_log_ingest_state table."""
    if engine is None:
        engine = _get_fallback_engine()

    is_postgres = engine.dialect.name == "postgresql"
    pk_type = "SERIAL PRIMARY KEY" if is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"

    inspector = inspect(engine)
    logger.info("Migration 058: SD-card backfill schema...")

    # --- livelink_devices columns ---
    if inspector.has_table("livelink_devices"):
        with engine.begin() as conn:
            if not _column_exists(inspector, "livelink_devices", "device_address"):
                conn.execute(
                    text("ALTER TABLE livelink_devices ADD COLUMN device_address VARCHAR(255)")
                )
                logger.info("  + livelink_devices.device_address")

            if not _column_exists(inspector, "livelink_devices", "sd_backfill_enabled"):
                default = "FALSE" if is_postgres else "0"
                conn.execute(
                    text(
                        f"ALTER TABLE livelink_devices ADD COLUMN sd_backfill_enabled BOOLEAN DEFAULT {default}"
                    )
                )
                logger.info("  + livelink_devices.sd_backfill_enabled")

    # --- sd_log_ingest_state table ---
    if not inspector.has_table("sd_log_ingest_state"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"CREATE TABLE sd_log_ingest_state ("
                    f"id {pk_type}, "
                    f"device_id VARCHAR(20) NOT NULL, "
                    f"filename VARCHAR(255) NOT NULL, "
                    f"last_timestamp INTEGER DEFAULT 0, "
                    f"rows_ingested INTEGER DEFAULT 0, "
                    f"completed BOOLEAN DEFAULT 0, "
                    f"updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                    f")"
                )
            )
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX uq_sd_log_ingest_device_file "
                    "ON sd_log_ingest_state (device_id, filename)"
                )
            )
            logger.info("  + sd_log_ingest_state table + unique index")

    logger.info("Migration 058 complete.")


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError(
        "Migration 058 is forward-only. Restore from a pre-058 backup if needed."
    )


if __name__ == "__main__":
    upgrade()

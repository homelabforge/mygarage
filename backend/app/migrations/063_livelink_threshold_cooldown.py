"""Add ``livelink_parameters.warning_last_notified_at`` for alert cooldown.

Task 12 (migration 062) backfilled `param_class` on existing telemetry
parameters, which makes the previously-inert `TelemetryService.check_thresholds`
path reachable in anger: WiCAN can emit several telemetry frames a minute, and
without a cooldown every breaching frame would dispatch a fresh notification.

This migration adds a single nullable timestamp column that
`check_thresholds` uses to enforce a 30-minute per-parameter cooldown: the
column is stamped with the current UTC time only when a notification is
actually sent, and dispatch is skipped while a prior stamp is still within
the cooldown window.

Idempotent (column-exists guard before ADD COLUMN), dialect-aware (SQLite +
PostgreSQL — ``DATETIME`` is translated to ``TIMESTAMP`` for PG, mirroring
migration 054's ``_PG_TYPE_REWRITES`` pattern), forward-only.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

_COLUMN_TYPE_SQLITE = "DATETIME"
_COLUMN_TYPE_PG = "TIMESTAMP"


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
    """Add the nullable `warning_last_notified_at` cooldown column."""
    if engine is None:
        engine = _get_fallback_engine()

    print("Migration 063: add livelink_parameters.warning_last_notified_at...")

    inspector = inspect(engine)
    if not inspector.has_table("livelink_parameters"):
        print("  = livelink_parameters table absent, skipping")
        print("Migration 063 complete.")
        return

    if _column_exists(inspector, "livelink_parameters", "warning_last_notified_at"):
        print("  = warning_last_notified_at already present, skipping")
        print("Migration 063 complete.")
        return

    column_type = _COLUMN_TYPE_PG if engine.dialect.name == "postgresql" else _COLUMN_TYPE_SQLITE
    with engine.begin() as conn:
        conn.execute(
            text(
                f"ALTER TABLE livelink_parameters ADD COLUMN warning_last_notified_at {column_type}"
            )
        )
    print("  + Added livelink_parameters.warning_last_notified_at (nullable)")
    print("Migration 063 complete.")


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError(
        "Migration 063 is forward-only. It only adds a nullable column with "
        "no prior state; there is nothing meaningful to restore."
    )


if __name__ == "__main__":
    upgrade()

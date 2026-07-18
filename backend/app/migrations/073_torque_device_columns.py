"""Add Torque device support columns.

Adds ``kind`` + ``torque_device_id`` to ``livelink_devices`` and
``external_session_id`` to ``drive_sessions``. ``kind`` defaults to 'wican' so
existing rows stay valid.

FATAL: the ``LiveLinkDevice`` and ``DriveSession`` models map these columns, so
every SELECT of those tables includes them. A silently-missing column would 500
all device/session reads. The runner log-and-continues on non-FATAL failure
(``database.py``; no ``strict_migrations``), so halting startup is correct.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

FATAL = True


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def _has_column(inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade(engine=None):
    if engine is None:
        engine = _get_fallback_engine()
    inspector = inspect(engine)
    with engine.begin() as conn:
        if inspector.has_table("livelink_devices"):
            if not _has_column(inspector, "livelink_devices", "kind"):
                # String literal default is valid on both SQLite and PG.
                conn.execute(
                    text(
                        "ALTER TABLE livelink_devices ADD COLUMN kind VARCHAR(10) NOT NULL DEFAULT 'wican'"
                    )
                )
            if not _has_column(inspector, "livelink_devices", "torque_device_id"):
                conn.execute(
                    text("ALTER TABLE livelink_devices ADD COLUMN torque_device_id VARCHAR(40)")
                )
        if inspector.has_table("drive_sessions"):
            if not _has_column(inspector, "drive_sessions", "external_session_id"):
                conn.execute(
                    text("ALTER TABLE drive_sessions ADD COLUMN external_session_id VARCHAR(64)")
                )
            # One DriveSession per Torque session id per device (R1-H2). NULLs distinct
            # on both dialects → WiCAN rows never collide. IF NOT EXISTS works on both.
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_drive_session_external "
                    "ON drive_sessions (device_id, external_session_id)"
                )
            )


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 073 is forward-only.")


if __name__ == "__main__":
    upgrade()

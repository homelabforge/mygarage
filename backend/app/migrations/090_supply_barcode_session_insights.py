"""Add supply barcode + LiveLink drive-session insight columns.

FATAL: DriveSession / Supply models gain columns referenced by ORM; existing
DBs need the migration so queries and session end aggregates don't fail.
"""

from __future__ import annotations

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
    if table not in inspector.get_table_names():
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade(engine=None):
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        inspector = inspect(engine)
        print("Adding supply barcode + drive session insights...")

        if "supplies" in inspector.get_table_names() and not _has_column(
            inspector, "supplies", "barcode"
        ):
            conn.execute(text("ALTER TABLE supplies ADD COLUMN barcode VARCHAR(64)"))
            print("  → supplies.barcode added")
        else:
            print("  → supplies.barcode already present or table missing, skipping")

        if "supplies" in inspector.get_table_names():
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS idx_supplies_barcode ON supplies (barcode)")
            )

        for col, typ in (
            ("idle_seconds", "INTEGER"),
            ("harsh_accel_count", "INTEGER"),
            ("harsh_brake_count", "INTEGER"),
        ):
            if "drive_sessions" in inspector.get_table_names() and not _has_column(
                inspector, "drive_sessions", col
            ):
                conn.execute(text(f"ALTER TABLE drive_sessions ADD COLUMN {col} {typ}"))
                print(f"  → drive_sessions.{col} added")
            else:
                print(f"  → drive_sessions.{col} already present or table missing, skipping")

        print("Migration 090 complete")

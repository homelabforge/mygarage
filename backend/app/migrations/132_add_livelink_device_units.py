"""Add livelink_device_units: the units each LiveLink device declared on the wire (R12).

Normally created earlier by Base.metadata.create_all, so the has_table guard
skips it. Non-FATAL for the same reason: a failure here leaves no table
missing, and no existing table changes. Column types, nullability, defaults and
the foreign key match app/models/livelink_device_unit.py exactly, because
either one may create the table first.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

FATAL = False


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None):
    if engine is None:
        engine = _get_fallback_engine()

    inspector = inspect(engine)
    if not inspector.has_table("livelink_devices"):
        return
    if inspector.has_table("livelink_device_units"):
        return

    is_pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts = "TIMESTAMP" if is_pg else "DATETIME"

    with engine.begin() as conn:
        conn.execute(
            text(f"""
            CREATE TABLE livelink_device_units (
                id {pk},
                device_id VARCHAR(20) NOT NULL,
                param_key VARCHAR(100) NOT NULL,
                unit VARCHAR(20),
                param_class VARCHAR(50),
                source VARCHAR(10) NOT NULL
                    CONSTRAINT check_livelink_device_units_source
                    CHECK (source IN ('wire', 'legacy')),
                created_at {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at {ts},
                CONSTRAINT uq_livelink_device_units_device_param UNIQUE (device_id, param_key),
                FOREIGN KEY (device_id) REFERENCES livelink_devices(device_id) ON DELETE CASCADE
            )
        """)
        )


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 132 is forward-only.")


if __name__ == "__main__":
    upgrade()

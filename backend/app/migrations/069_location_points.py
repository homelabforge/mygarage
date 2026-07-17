"""Create location_points table for Torque GPS breadcrumbs (#118).

New table: created by Base.metadata.create_all before the runner in prod, so
this migration's has_table guard skips there. It exists for PG-CI index parity,
test coverage, and documentation. Non-FATAL by design.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


def _get_fallback_engine():
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None):
    if engine is None:
        engine = _get_fallback_engine()
    is_pg = engine.dialect.name == "postgresql"
    pk_type = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts_type = "TIMESTAMP" if is_pg else "DATETIME"
    inspector = inspect(engine)
    if inspector.has_table("location_points"):
        return
    with engine.begin() as conn:
        conn.execute(
            text(f"""
            CREATE TABLE location_points (
                id {pk_type},
                vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
                drive_session_id INTEGER REFERENCES drive_sessions(id) ON DELETE CASCADE,
                source VARCHAR(10) NOT NULL,
                timestamp {ts_type} NOT NULL,
                latitude NUMERIC(9, 6) NOT NULL,
                longitude NUMERIC(9, 6) NOT NULL,
                speed NUMERIC(6, 2),
                heading NUMERIC(5, 1),
                altitude NUMERIC(7, 1),
                received_at {ts_type} DEFAULT CURRENT_TIMESTAMP
            )
        """)
        )
        conn.execute(
            text("CREATE INDEX idx_location_points_vin_time ON location_points (vin, timestamp)")
        )
        conn.execute(
            text("CREATE INDEX idx_location_points_session ON location_points (drive_session_id)")
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX uq_location_points_dedup ON location_points (vin, timestamp, source)"
            )
        )


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 069 is forward-only.")


if __name__ == "__main__":
    upgrade()

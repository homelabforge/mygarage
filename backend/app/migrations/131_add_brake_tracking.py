"""Add brake tracking: axle setup, brake measurements and brake jobs (#202).

Normally created earlier by Base.metadata.create_all, so the has_table guards
skip them. Non-FATAL for the same reason: a failure here leaves no table
missing, and no existing table changes. Column types, nullability, defaults and
foreign keys match app/models/brake.py exactly, because either one may create a
table first.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

FATAL = False

_POSITION_CHECK = "position IN ('FL', 'FR', 'RL', 'RR')"
_TYPE_CHECK = "brake_type IN ('disc', 'drum')"


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
    if not inspector.has_table("vehicles"):
        return

    is_pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts = "TIMESTAMP" if is_pg else "DATETIME"
    false = "FALSE" if is_pg else "0"
    vin = "VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE"

    with engine.begin() as conn:
        if not inspector.has_table("brake_axles"):
            conn.execute(
                text(f"""
                CREATE TABLE brake_axles (
                    id {pk},
                    vin {vin},
                    axle VARCHAR(5) NOT NULL
                        CONSTRAINT check_brake_axles_axle CHECK (axle IN ('front', 'rear')),
                    brake_type VARCHAR(4) NOT NULL
                        CONSTRAINT check_brake_axles_brake_type CHECK ({_TYPE_CHECK}),
                    min_thickness_mm NUMERIC(4,2) NOT NULL,
                    new_thickness_mm NUMERIC(4,2) NOT NULL,
                    rotor_min_mm NUMERIC(5,2),
                    drum_max_mm NUMERIC(6,2),
                    created_at {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at {ts},
                    CONSTRAINT uq_brake_axles_vin_axle UNIQUE (vin, axle)
                )
            """)
            )

        if not inspector.has_table("brake_jobs"):
            conn.execute(
                text(f"""
                CREATE TABLE brake_jobs (
                    id {pk},
                    vin {vin},
                    position VARCHAR(2) NOT NULL
                        CONSTRAINT check_brake_jobs_position CHECK ({_POSITION_CHECK}),
                    brake_type VARCHAR(4) NOT NULL
                        CONSTRAINT check_brake_jobs_brake_type CHECK ({_TYPE_CHECK}),
                    performed_on DATE NOT NULL,
                    odometer_km NUMERIC(10,2),
                    engine_hours NUMERIC(10,1),
                    friction_replaced BOOLEAN NOT NULL DEFAULT {false},
                    surface VARCHAR(10)
                        CONSTRAINT check_brake_jobs_surface
                        CHECK (surface IS NULL OR surface IN ('replaced', 'resurfaced')),
                    notes TEXT,
                    created_at {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_brake_jobs_vin_position "
                "ON brake_jobs (vin, position)"
            )
        )

        if not inspector.has_table("brake_measurements"):
            conn.execute(
                text(f"""
                CREATE TABLE brake_measurements (
                    id {pk},
                    vin {vin},
                    position VARCHAR(2) NOT NULL
                        CONSTRAINT check_brake_measurements_position CHECK ({_POSITION_CHECK}),
                    recorded_at DATE NOT NULL,
                    odometer_km NUMERIC(10,2),
                    engine_hours NUMERIC(10,1),
                    inner_pad_mm NUMERIC(4,2),
                    outer_pad_mm NUMERIC(4,2),
                    rotor_mm NUMERIC(5,2),
                    shoe_mm NUMERIC(4,2),
                    drum_mm NUMERIC(6,2),
                    brake_job_id INTEGER REFERENCES brake_jobs(id) ON DELETE CASCADE,
                    notes TEXT,
                    created_at {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_brake_measurements_vin_position "
                "ON brake_measurements (vin, position)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_brake_measurements_brake_job "
                "ON brake_measurements (brake_job_id)"
            )
        )


def downgrade():  # pragma: no cover
    raise NotImplementedError("Migration 131 is forward-only.")


if __name__ == "__main__":
    upgrade()

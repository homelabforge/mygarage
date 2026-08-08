"""Add tires + tire_readings tables for position/tread/DOT tracking.

FATAL: Tire ORM models are imported at app startup; missing tables would 500
every tire route and break schema parity tests.
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


def upgrade(engine=None) -> None:
    if engine is None:
        engine = _get_fallback_engine()

    inspector = inspect(engine)
    if not inspector.has_table("vehicles"):
        return

    is_pg = engine.dialect.name == "postgresql"
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"

    with engine.begin() as conn:
        if not inspector.has_table("tires"):
            conn.execute(
                text(
                    f"""
                    CREATE TABLE tires (
                        id {pk},
                        vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
                        position VARCHAR(10) NOT NULL,
                        brand VARCHAR(80),
                        model_name VARCHAR(80),
                        size VARCHAR(40),
                        dot_code VARCHAR(20),
                        installed_date DATE,
                        tread_depth_mm NUMERIC(5, 2),
                        pressure_kpa NUMERIC(7, 2),
                        min_tread_mm NUMERIC(5, 2) DEFAULT 2.0,
                        notes TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        CONSTRAINT uq_tires_vin_position UNIQUE (vin, position)
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX idx_tires_vin ON tires (vin)"))
            print("✓ Created tires table")
        else:
            print("✓ tires already exists")

        # Re-inspect after possible create
        inspector = inspect(engine)
        if not inspector.has_table("tire_readings"):
            conn.execute(
                text(
                    f"""
                    CREATE TABLE tire_readings (
                        id {pk},
                        tire_id INTEGER NOT NULL REFERENCES tires(id) ON DELETE CASCADE,
                        vin VARCHAR(17) NOT NULL REFERENCES vehicles(vin) ON DELETE CASCADE,
                        position VARCHAR(10) NOT NULL,
                        recorded_at DATE NOT NULL,
                        odometer_km NUMERIC(10, 2),
                        tread_depth_mm NUMERIC(5, 2) NOT NULL,
                        pressure_kpa NUMERIC(7, 2),
                        notes TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX idx_tire_readings_tire ON tire_readings (tire_id)"))
            conn.execute(text("CREATE INDEX idx_tire_readings_vin ON tire_readings (vin)"))
            print("✓ Created tire_readings table")
        else:
            print("✓ tire_readings already exists")

    print("✓ Migration 085 (tire tracking) completed")


def downgrade() -> None:
    print("Downgrade not supported — restore from backup")


if __name__ == "__main__":
    upgrade()

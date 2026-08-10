"""Add external_vehicles table for customer / family reference records.

FATAL: the ExternalVehicle model is imported into Base.metadata; without this
table, create_all on fresh DBs is fine, but existing deployments need the
migration and startup should fail loudly if the table cannot be created.
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


def upgrade(engine=None):
    """Create external_vehicles if missing."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        inspector = inspect(engine)
        print("Adding external_vehicles support...")

        if "external_vehicles" in inspector.get_table_names():
            print("  → external_vehicles already exists, skipping")
            return

        dialect = engine.dialect.name
        if dialect == "postgresql":
            conn.execute(
                text(
                    """
                    CREATE TABLE external_vehicles (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        kind VARCHAR(20) NOT NULL,
                        nickname VARCHAR(100) NOT NULL,
                        year INTEGER,
                        make VARCHAR(50),
                        model VARCHAR(50),
                        vehicle_type VARCHAR(30),
                        contact_name VARCHAR(100),
                        contact_phone VARCHAR(40),
                        notes TEXT,
                        last_service_note VARCHAR(200),
                        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW() NOT NULL,
                        updated_at TIMESTAMP WITHOUT TIME ZONE
                    )
                    """
                )
            )
        else:
            conn.execute(
                text(
                    """
                    CREATE TABLE external_vehicles (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        kind VARCHAR(20) NOT NULL,
                        nickname VARCHAR(100) NOT NULL,
                        year INTEGER,
                        make VARCHAR(50),
                        model VARCHAR(50),
                        vehicle_type VARCHAR(30),
                        contact_name VARCHAR(100),
                        contact_phone VARCHAR(40),
                        notes TEXT,
                        last_service_note VARCHAR(200),
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                        updated_at DATETIME
                    )
                    """
                )
            )

        conn.execute(text("CREATE INDEX ix_external_vehicles_user_id ON external_vehicles (user_id)"))
        conn.execute(text("CREATE INDEX ix_external_vehicles_kind ON external_vehicles (kind)"))
        print("  ✓ Created external_vehicles table")
        print("\n✓ External vehicles migration completed successfully")


def downgrade():
    print("Downgrade not supported for external_vehicles")


if __name__ == "__main__":
    upgrade()

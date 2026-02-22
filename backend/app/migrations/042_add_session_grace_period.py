"""Add session grace period for WiFi drop resilience.

Adds pending_offline_at column to livelink_devices and a setting
for configurable grace period duration. Prevents phantom micro-sessions
from brief WiFi disconnections (WiCAN Discussion #181).
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


def upgrade():
    """Add grace period column and setting."""
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    engine = create_engine(database_url)

    with engine.begin() as conn:
        # Add pending_offline_at column to livelink_devices
        inspector = inspect(engine)
        columns = [col["name"] for col in inspector.get_columns("livelink_devices")]

        if "pending_offline_at" not in columns:
            conn.execute(
                text("ALTER TABLE livelink_devices ADD COLUMN pending_offline_at DATETIME")
            )
            print("  Added column: livelink_devices.pending_offline_at")
        else:
            print("  → Column pending_offline_at already exists, skipping")

        # Add grace period setting
        result = conn.execute(
            text("SELECT key FROM settings WHERE key = :key"),
            {"key": "livelink_session_grace_period_seconds"},
        )
        if result.fetchone():
            print("  → Setting livelink_session_grace_period_seconds already exists, skipping")
        else:
            conn.execute(
                text("""
                    INSERT INTO settings (key, value, category, description, encrypted)
                    VALUES (:key, :value, :category, :description, :encrypted)
                """),
                {
                    "key": "livelink_session_grace_period_seconds",
                    "value": "60",
                    "category": "livelink",
                    "description": "Seconds to wait before ending a session after ECU offline "
                    "(prevents phantom sessions from WiFi drops)",
                    "encrypted": 0,
                },
            )
            print("  Added setting: livelink_session_grace_period_seconds")


def downgrade():
    """Remove grace period column and setting (not recommended)."""
    print("  Downgrade not supported - column and setting retained for safety")


if __name__ == "__main__":
    upgrade()

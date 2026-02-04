"""Add MQTT settings for LiveLink MQTT integration.

Adds settings to support MQTT subscription from WiCAN devices
as an alternative to HTTPS POST ingestion.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, text


def upgrade():
    """Add MQTT-related settings to the settings table."""
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    engine = create_engine(database_url)

    mqtt_settings = [
        (
            "livelink_mqtt_enabled",
            "false",
            "livelink",
            "Enable MQTT subscription for WiCAN devices (alternative to HTTPS POST)",
            False,
        ),
        (
            "livelink_mqtt_broker_host",
            "",
            "livelink",
            "MQTT broker hostname or IP address",
            False,
        ),
        (
            "livelink_mqtt_broker_port",
            "1883",
            "livelink",
            "MQTT broker port (default: 1883, TLS: 8883)",
            False,
        ),
        (
            "livelink_mqtt_username",
            "",
            "livelink",
            "MQTT broker username (optional)",
            False,
        ),
        (
            "livelink_mqtt_password",
            "",
            "livelink",
            "MQTT broker password (optional)",
            True,
        ),
        (
            "livelink_mqtt_topic_prefix",
            "wican",
            "livelink",
            "MQTT topic prefix (default: wican)",
            False,
        ),
        (
            "livelink_mqtt_use_tls",
            "false",
            "livelink",
            "Use TLS/SSL for MQTT connection",
            False,
        ),
    ]

    with engine.begin() as conn:
        for key, value, category, description, encrypted in mqtt_settings:
            # Check if setting already exists (idempotency)
            result = conn.execute(text("SELECT key FROM settings WHERE key = :key"), {"key": key})
            if result.fetchone():
                print(f"  → Setting {key} already exists, skipping")
                continue

            conn.execute(
                text("""
                    INSERT INTO settings (key, value, category, description, encrypted)
                    VALUES (:key, :value, :category, :description, :encrypted)
                """),
                {
                    "key": key,
                    "value": value,
                    "category": category,
                    "description": description,
                    "encrypted": 1 if encrypted else 0,
                },
            )
            print(f"  Added setting: {key}")


def downgrade():
    """Remove MQTT settings (not recommended)."""
    print("  Downgrade not supported - settings retained for safety")


if __name__ == "__main__":
    upgrade()

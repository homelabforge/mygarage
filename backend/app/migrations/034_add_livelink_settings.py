"""Add LiveLink settings to settings table.

This migration adds the default LiveLink configuration settings:
- livelink_enabled: Master enable/disable toggle
- livelink_global_token_hash: Hashed global API token
- livelink_telemetry_retention_days: Raw data retention period
- livelink_session_timeout_minutes: Timeout for session detection
- livelink_daily_aggregation_enabled: Enable daily rollup aggregates
- notify_livelink_device_offline: Enable offline device notifications
- notify_livelink_threshold_alerts: Enable parameter threshold alerts
- notify_livelink_firmware_update: Enable firmware update notifications
- notify_livelink_new_device: Enable new device discovery notifications
- livelink_alert_cooldown_minutes: Cooldown between repeated alerts
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, text


def upgrade():
    """Add LiveLink settings to settings table."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    engine = create_engine(database_url)

    # LiveLink settings to add with defaults
    livelink_settings = [
        {
            "key": "livelink_enabled",
            "value": "false",
            "category": "livelink",
            "description": "Enable LiveLink WiCAN telemetry integration",
        },
        {
            "key": "livelink_global_token_hash",
            "value": None,  # Will be set when token is generated
            "category": "livelink",
            "description": "SHA-256 hash of global LiveLink API token",
        },
        {
            "key": "livelink_telemetry_retention_days",
            "value": "90",
            "category": "livelink",
            "description": "Days to retain raw telemetry data (30-365)",
        },
        {
            "key": "livelink_session_timeout_minutes",
            "value": "5",
            "category": "livelink",
            "description": "Minutes of inactivity before closing a drive session",
        },
        {
            "key": "livelink_daily_aggregation_enabled",
            "value": "true",
            "category": "livelink",
            "description": "Enable daily telemetry aggregation for long-term charts",
        },
        {
            "key": "livelink_device_offline_timeout_minutes",
            "value": "15",
            "category": "livelink",
            "description": "Minutes before marking device as offline",
        },
        {
            "key": "notify_livelink_device_offline",
            "value": "true",
            "category": "livelink",
            "description": "Send notification when LiveLink device goes offline",
        },
        {
            "key": "notify_livelink_threshold_alerts",
            "value": "true",
            "category": "livelink",
            "description": "Send notifications for parameter threshold breaches",
        },
        {
            "key": "notify_livelink_firmware_update",
            "value": "true",
            "category": "livelink",
            "description": "Send notification when WiCAN firmware update available",
        },
        {
            "key": "notify_livelink_new_device",
            "value": "true",
            "category": "livelink",
            "description": "Send notification when new WiCAN device discovered",
        },
        {
            "key": "livelink_alert_cooldown_minutes",
            "value": "30",
            "category": "livelink",
            "description": "Minimum minutes between repeated alert notifications",
        },
        {
            "key": "livelink_firmware_check_enabled",
            "value": "true",
            "category": "livelink",
            "description": "Automatically check for WiCAN firmware updates daily",
        },
    ]

    with engine.begin() as conn:
        # Check if settings table exists
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='settings'")
        )
        if not result.fetchone():
            print("  settings table does not exist, skipping")
            return

        # Get existing setting keys
        result = conn.execute(text("SELECT key FROM settings WHERE category = 'livelink'"))
        existing_keys = {row[0] for row in result.fetchall()}

        # Insert settings that don't exist
        for setting in livelink_settings:
            if setting["key"] in existing_keys:
                print(f"  Setting {setting['key']} already exists, skipping")
                continue

            conn.execute(
                text("""
                    INSERT INTO settings (key, value, category, description, encrypted)
                    VALUES (:key, :value, :category, :description, 0)
                """),
                {
                    "key": setting["key"],
                    "value": setting["value"],
                    "category": setting["category"],
                    "description": setting["description"],
                },
            )
            print(f"  Added setting: {setting['key']}")

    print("  Migration 034 complete - LiveLink settings added")


if __name__ == "__main__":
    upgrade()

"""Add webhook_ingest_token setting for inbound fuel/odometer/reminder webhooks.

Non-FATAL: settings are key/value; missing key just means webhooks stay disabled
until the user generates a token in Settings.
"""

from __future__ import annotations

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


def upgrade(engine=None) -> None:
    if engine is None:
        engine = _get_fallback_engine()

    inspector = inspect(engine)
    if not inspector.has_table("settings"):
        return

    with engine.begin() as conn:
        existing = conn.execute(
            text("SELECT 1 FROM settings WHERE key = 'webhook_ingest_token'")
        ).fetchone()
        if existing:
            print("✓ webhook_ingest_token setting already present")
            return
        conn.execute(
            text(
                """
                INSERT INTO settings (key, value, category, encrypted, description)
                VALUES (
                    'webhook_ingest_token',
                    '',
                    'integrations',
                    true,
                    'Shared secret for POST /api/v1/webhooks/* (HA, n8n, Telegram bot)'
                )
                """
            )
        )
        existing_tg = conn.execute(
            text("SELECT 1 FROM settings WHERE key = 'telegram_inbound_enabled'")
        ).fetchone()
        if not existing_tg:
            conn.execute(
                text(
                    """
                    INSERT INTO settings (key, value, category, encrypted, description)
                    VALUES (
                        'telegram_inbound_enabled',
                        'false',
                        'integrations',
                        false,
                        'Accept structured fuel commands via Telegram bot webhook'
                    )
                    """
                )
            )
    print("✓ Migration 087 (webhook ingest settings) completed")


def downgrade() -> None:
    print("Downgrade not supported — restore from backup")


if __name__ == "__main__":
    upgrade()

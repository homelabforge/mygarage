"""Add widget_api_keys table for homepage widget integration.

Creates a new table to store user-managed read-only API keys used by
gethomepage (or similar dashboards) to poll /api/widget/* endpoints.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None):
    """Create widget_api_keys table with dialect-aware DDL."""
    if engine is None:
        engine = _get_fallback_engine()

    is_postgres = engine.dialect.name == "postgresql"
    pk_type = "SERIAL PRIMARY KEY" if is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"

    with engine.begin() as conn:
        inspector = inspect(engine)
        print("Widget API keys migration...")

        if inspector.has_table("widget_api_keys"):
            print("  → widget_api_keys table already exists, skipping")
            return

        conn.execute(
            text(f"""
            CREATE TABLE widget_api_keys (
                id {pk_type},
                user_id INTEGER NOT NULL,
                name VARCHAR(100) NOT NULL,
                key_hash VARCHAR(64) NOT NULL,
                key_prefix VARCHAR(16) NOT NULL,
                scope VARCHAR(20) NOT NULL DEFAULT 'all_vehicles',
                allowed_vins TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_used_at TIMESTAMP,
                revoked_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        )
        print("  ✓ Created widget_api_keys table")

        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_widget_api_keys_user_id ON widget_api_keys(user_id)"
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_widget_api_keys_key_hash "
                "ON widget_api_keys(key_hash)"
            )
        )
        print("  ✓ Ensured indexes on widget_api_keys")

        print("\n✓ Widget API keys migration completed")


def downgrade(engine=None):
    """Remove widget_api_keys table (for testing/rollback only)."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        print("Rolling back widget_api_keys migration...")
        conn.execute(text("DROP TABLE IF EXISTS widget_api_keys"))
        print("✓ Rollback completed")


if __name__ == "__main__":
    upgrade()

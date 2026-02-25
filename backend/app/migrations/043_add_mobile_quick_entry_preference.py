"""Add mobile quick entry preference to users.

Adds mobile_quick_entry_enabled column to the users table.
When enabled, mobile users are redirected to the Quick Entry
page instead of the dashboard immediately after login.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


def upgrade():
    """Add mobile_quick_entry_enabled column to users table."""
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    engine = create_engine(database_url)

    with engine.begin() as conn:
        inspector = inspect(engine)
        columns = [col["name"] for col in inspector.get_columns("users")]

        if "mobile_quick_entry_enabled" not in columns:
            conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN mobile_quick_entry_enabled INTEGER NOT NULL DEFAULT 1"
                )
            )
            print("  Added column: users.mobile_quick_entry_enabled")
        else:
            print("  → Column mobile_quick_entry_enabled already exists, skipping")


def downgrade():
    """Remove mobile_quick_entry_enabled column (not supported in SQLite)."""
    print("  Downgrade not supported - column retained for safety")


if __name__ == "__main__":
    upgrade()

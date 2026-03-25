"""Add i18n preferences (language and currency) to user settings.

This migration adds per-user language and currency preferences.
All monetary values remain stored as-is; currency_code controls display formatting only.
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
    """Add language and currency_code columns to users table."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        inspector = inspect(engine)
        print("Adding i18n user preferences...")

        existing_columns = {col["name"] for col in inspector.get_columns("users")}

        if "language" not in existing_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN language VARCHAR(10) DEFAULT 'en'"))
            print("  ✓ Added language column to users table")

            # Backfill NULLs
            result = conn.execute(text("UPDATE users SET language = 'en' WHERE language IS NULL"))
            print(f"  ✓ Set {result.rowcount} existing user(s) to language='en'")
        else:
            print("  → language column already exists, skipping")

        if "currency_code" not in existing_columns:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN currency_code VARCHAR(3) DEFAULT 'USD'")
            )
            print("  ✓ Added currency_code column to users table")

            # Backfill NULLs
            result = conn.execute(
                text("UPDATE users SET currency_code = 'USD' WHERE currency_code IS NULL")
            )
            print(f"  ✓ Set {result.rowcount} existing user(s) to currency_code='USD'")
        else:
            print("  → currency_code column already exists, skipping")

        print("\n✓ i18n user preferences migration completed successfully")


def downgrade():
    """Rollback not supported."""
    print("Downgrade not supported for ALTER TABLE ADD COLUMN")


if __name__ == "__main__":
    upgrade()

"""Add per-account UI accent preference (accent_color) to user settings.

Adds a per-user theme accent (one of the six keys in the frontend's
``src/constants/accents.ts``). Display-only — the accent is a CSS custom-property
choice with no bearing on stored data. Mirrors migration 066 (time_format).

FATAL: the ``User`` model declares ``accent_color`` as a non-nullable column and
reads it on every auth path (it is serialized in the ``UserResponse`` returned by
``/auth/me``). The migration runner log-and-continues on non-FATAL failure
(``database.py``; there is no ``strict_migrations`` enforcement), so a silent
failure would boot the app against a missing column. Halting startup is the
correct behavior for a column the model hard-depends on.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

FATAL = True


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None):
    """Add accent_color column to users table (default 'blue')."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        inspector = inspect(engine)
        print("Adding UI accent preference support...")

        existing_columns = {col["name"] for col in inspector.get_columns("users")}

        if "accent_color" in existing_columns:
            print("  → accent_color column already exists, skipping migration")
            return

        # Add accent_color column (default: blue). VARCHAR is valid on both
        # SQLite and PostgreSQL, so no dialect-specific type rewrite is needed.
        conn.execute(text("ALTER TABLE users ADD COLUMN accent_color VARCHAR(20) DEFAULT 'blue'"))
        print("  ✓ Added accent_color column to users table")

        # Backfill any existing users to the default accent.
        result = conn.execute(
            text("UPDATE users SET accent_color = 'blue' WHERE accent_color IS NULL")
        )
        print(f"  ✓ Set {result.rowcount} existing user(s) to the default accent")

        print("\n✓ Accent preference migration completed successfully")


def downgrade():
    """Rollback not supported."""
    print("Downgrade not supported for ALTER TABLE ADD COLUMN")


if __name__ == "__main__":
    upgrade()

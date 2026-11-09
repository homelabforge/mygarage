"""Add per-account light/dark theme preference (theme) to user settings.

Adds a per-user UI theme ('light' or 'dark'). Display-only — a CSS class choice
with no bearing on stored data. Mirrors the accent_color pattern (migrations
078/081) but is added nullable from the start (no DB DEFAULT): NULL = the user
has never explicitly picked a theme, so the client's localStorage seed / default
wins and useThemeSync must NOT override it. A non-null value is an explicit
choice that syncs across devices. The ``User`` model declares it
``Mapped[str | None]``, so the ORM always sends an explicit value on insert
(NULL when unset), and the theme toggle's PUT /auth/me stores an explicit value.

FATAL: the ``User`` model declares ``theme`` and reads it on every auth path (it
is serialized in the ``UserResponse`` returned by ``/auth/me``). The migration
runner log-and-continues on non-FATAL failure (``database.py``; there is no
``strict_migrations`` enforcement), so a silent failure would boot the app
against a missing column and every user query would raise. Halting startup is
the correct behavior for a column the model hard-depends on.
"""

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = True


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None):
    """Add nullable theme column to users table (no DB default)."""
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()

    if not inspect(engine).has_table("users"):
        print("  → users table absent, skipping theme migration")
        return

    with engine.begin() as conn:
        inspector = inspect(engine)
        print("Adding UI theme preference support...")

        existing_columns = {col["name"] for col in inspector.get_columns("users")}

        if "theme" in existing_columns:
            print("  → theme column already exists, skipping migration")
            return

        # Nullable, no DEFAULT — NULL means "never explicitly picked". VARCHAR is
        # valid on both SQLite and PostgreSQL, so no dialect-specific type rewrite
        # is needed.
        conn.execute(text("ALTER TABLE users ADD COLUMN theme VARCHAR(10)"))
        print("  ✓ Added theme column to users table")

        print("\n✓ Theme preference migration completed successfully")


def downgrade():
    """Rollback not supported."""
    print("Downgrade not supported for ALTER TABLE ADD COLUMN")


if __name__ == "__main__":
    upgrade()

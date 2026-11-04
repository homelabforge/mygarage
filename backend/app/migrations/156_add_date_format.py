"""Add users.date_format: the order of day and month in this person's dates.

'mdy' (10/24/2026) or 'dmy' (24/10/2026), validated by Pydantic, not a DB CHECK.
Existing users get 'mdy', the order English dates have always used, so nothing
changes on upgrade. Languages whose own convention is day-first ignore it.

FATAL: the ORM maps the column as NOT NULL and selects it on every auth path,
so a silent failure would boot the app against a missing column (the reason 066
and 120 are FATAL too). ``ADD COLUMN ... NOT NULL DEFAULT`` fills existing rows
on both SQLite and PostgreSQL, so no backfill is needed. Idempotent: the column
is added only when absent.
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
    """Add users.date_format (NOT NULL, default 'mdy')."""
    if engine is None:
        engine = _get_fallback_engine()

    if not inspect(engine).has_table("users"):
        return

    with engine.begin() as conn:
        existing = {col["name"] for col in inspect(engine).get_columns("users")}
        if "date_format" not in existing:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN date_format VARCHAR(10) NOT NULL DEFAULT 'mdy'")
            )
            print("  ✓ Added users.date_format (default 'mdy')")
        else:
            print("  → date_format already exists, skipping")


def downgrade():
    """Rollback not supported."""
    print("Downgrade not supported for ALTER TABLE ADD COLUMN")


if __name__ == "__main__":
    upgrade()

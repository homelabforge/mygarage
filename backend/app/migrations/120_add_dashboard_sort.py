"""Add users.dashboard_sort: the order this person's dashboard opens in.

One of the four orders the dashboard's sort menu offers (validated by Pydantic,
not a DB CHECK). Existing users get 'name', the order the dashboard has always
opened in, so nothing changes on upgrade. The menu itself still overrides it for
the rest of a browser tab's session.

FATAL: the ORM maps the column as NOT NULL and selects it on every auth path,
so a silent failure would boot the app against a missing column (the reason 066
is FATAL too). ``ADD COLUMN ... NOT NULL DEFAULT`` fills existing rows on both
SQLite and PostgreSQL, so no backfill is needed. Idempotent: the column is added
only when absent.
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
    """Add users.dashboard_sort (NOT NULL, default 'name')."""
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()

    if not inspect(engine).has_table("users"):
        return

    with engine.begin() as conn:
        existing = {col["name"] for col in inspect(engine).get_columns("users")}
        if "dashboard_sort" not in existing:
            conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN dashboard_sort VARCHAR(16) NOT NULL DEFAULT 'name'"
                )
            )
            print("  ✓ Added users.dashboard_sort (default 'name')")
        else:
            print("  → dashboard_sort already exists, skipping")


def downgrade():
    """Rollback not supported."""
    print("Downgrade not supported for ALTER TABLE ADD COLUMN")


if __name__ == "__main__":
    upgrade()

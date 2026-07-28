"""Reset defaulted users.accent_color 'blue' to NULL (unset != chosen).

Migration 078 added ``accent_color`` with a DB-level ``DEFAULT 'blue'`` and the
``User`` model declared it non-nullable, default 'blue'. That conflated two
states: "the user explicitly picked blue" and "the user never picked an accent."
useAccentSync applies any non-null DB accent over the client's localStorage
seed, so a defaulted 'blue' silently clobbers a real local choice (caught by the
P0 foundation accent e2e test once auth landed before the paint sample).

The accent picker is unreleased, so EVERY existing accent_color='blue' is a
default, never an explicit choice — reset them all to NULL ("unset"). The model
is now ``Mapped[str | None]`` (nullable, no default), so the ORM sends an
explicit value on insert (NULL when unset, the chosen key otherwise) and the
picker's PUT stores an explicit non-null value that syncs across devices. On
PostgreSQL we also drop the lingering column DEFAULT so an omitted-column insert
cannot reintroduce 'blue'; SQLite has no cheap DROP DEFAULT, but the ORM always
sends an explicit value, so the stale default is never exercised.

Non-FATAL: the column already exists and is now nullable; skipping this data
reset does not crash the app (useAccentSync would merely keep applying the old
default). Idempotent — runs once, before any explicit pick can exist.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

FATAL = False


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None):
    """Null out defaulted accent_color and (PG) drop the column default."""
    if engine is None:
        engine = _get_fallback_engine()

    if not inspect(engine).has_table("users"):
        return

    existing = {col["name"] for col in inspect(engine).get_columns("users")}
    if "accent_color" not in existing:
        print("  → users.accent_color absent (078 not applied), skipping")
        return

    with engine.begin() as conn:
        result = conn.execute(
            text("UPDATE users SET accent_color = NULL WHERE accent_color = 'blue'")
        )
        print(f"  ✓ Reset {result.rowcount} defaulted accent_color 'blue' → NULL")

        if engine.dialect.name == "postgresql":
            conn.execute(text("ALTER TABLE users ALTER COLUMN accent_color DROP DEFAULT"))
            print("  ✓ Dropped PostgreSQL column default on users.accent_color")

    print("\n✓ accent_color nullable-semantics migration completed successfully")


def downgrade():
    """Rollback not supported (cannot distinguish reset NULLs from originals)."""
    print("Downgrade not supported")


if __name__ == "__main__":
    upgrade()

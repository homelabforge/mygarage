"""Add users.oidc_relink_until: when an admin-approved SSO relink closes.

An SSO email or username match no longer links an account by itself, so when an
IdP account is re-created and its subject changes, the owner is locked out of
SSO. An admin (or the operator, through tools/oidc_allow_relink.py) arms a
one-time relink by setting this to a moment up to 30 minutes ahead; the next SSO
login that matches the account links it and clears the column. NULL, or a moment
in the past, means nothing is armed. Naive UTC, like the other users timestamps.

No backfill: every existing account starts unarmed, so nothing changes on
upgrade.

FATAL: the ORM maps the column and every `select(User)` names it, so a silent
failure would boot the app against a missing column and break every login.
Dialect-aware (``DATETIME`` on SQLite, ``TIMESTAMP`` on PostgreSQL, which rejects
``DATETIME``; see 054 and 064). Idempotent: the column is added only when absent.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine, inspect, text

FATAL = True

_COLUMN_TYPE_SQLITE = "DATETIME"
_COLUMN_TYPE_PG = "TIMESTAMP"


def _get_fallback_engine() -> Engine:
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine: Engine | None = None) -> None:
    """Add users.oidc_relink_until (nullable, no backfill)."""
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()

    if not inspect(engine).has_table("users"):
        return

    column_type = _COLUMN_TYPE_PG if engine.dialect.name == "postgresql" else _COLUMN_TYPE_SQLITE
    with engine.begin() as conn:
        existing = {col["name"] for col in inspect(engine).get_columns("users")}
        if "oidc_relink_until" not in existing:
            conn.execute(text(f"ALTER TABLE users ADD COLUMN oidc_relink_until {column_type}"))
            print("  ✓ Added users.oidc_relink_until (nullable)")
        else:
            print("  → oidc_relink_until already exists, skipping")


def downgrade() -> None:
    """Rollback not supported."""
    print("Downgrade not supported for ALTER TABLE ADD COLUMN")


if __name__ == "__main__":
    upgrade()

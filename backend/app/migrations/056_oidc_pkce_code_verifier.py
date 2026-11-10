"""Add ``oidc_states.code_verifier`` column for PKCE S256.

The OIDC login flow now generates a PKCE ``code_verifier`` at
authorization time and stores it alongside the state so the callback
handler can send it in the token exchange (RFC 7636). This migration
adds the column as nullable so any in-flight states issued before the
upgrade complete cleanly — those rows simply skip the PKCE leg, and
the next login starts a brand new flow that includes it.

Idempotent: column existence is checked before the ALTER. Works for
both SQLite and PostgreSQL.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import Engine, Inspector, create_engine, inspect, text

logger = logging.getLogger(__name__)


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def _column_exists(inspector: Inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade(engine: Engine | None = None) -> None:
    if engine is None:
        # Run standalone: it builds its own engine, so it closes it too.
        engine = _get_fallback_engine()
        try:
            return upgrade(engine)
        finally:
            engine.dispose()

    inspector = inspect(engine)

    print("OIDC PKCE code_verifier migration...")

    if not inspector.has_table("oidc_states"):
        print("  → oidc_states table not present yet, nothing to do")
        return

    if _column_exists(inspector, "oidc_states", "code_verifier"):
        print("  → code_verifier column already present, skipping")
        return

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE oidc_states ADD COLUMN code_verifier VARCHAR(128)"))
    print("  ✓ Added oidc_states.code_verifier (nullable)")
    print("✓ Migration 056 complete")


def downgrade() -> None:  # pragma: no cover
    raise NotImplementedError(
        "Migration 056 is forward-only. Restore from a pre-056 backup if needed."
    )

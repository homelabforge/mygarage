"""Security hardening migration - CSRF protection and OIDC state persistence.

This migration adds two new tables to support enhanced security:

1. csrf_tokens: Implements synchronizer token pattern for CSRF protection
2. oidc_states: Persists OIDC authentication flow state
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
    """Add security hardening tables."""
    if engine is None:
        engine = _get_fallback_engine()

    is_postgres = engine.dialect.name == "postgresql"
    pk_type = "SERIAL PRIMARY KEY" if is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"

    with engine.begin() as conn:
        inspector = inspect(engine)
        print("Security Hardening Migration - Creating CSRF and OIDC state tables...")

        # Create csrf_tokens table
        if not inspector.has_table("csrf_tokens"):
            conn.execute(
                text(f"""
                CREATE TABLE csrf_tokens (
                    id {pk_type},
                    token TEXT NOT NULL UNIQUE,
                    user_id INTEGER NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            )
            print("  ✓ Created csrf_tokens table")
        else:
            print("  → csrf_tokens table already exists")

        # Create indexes for csrf_tokens
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_csrf_token ON csrf_tokens(token)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_csrf_user_id ON csrf_tokens(user_id)"))
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_csrf_user_token ON csrf_tokens(user_id, token)")
        )
        print("  ✓ Ensured indexes on csrf_tokens")

        # Create oidc_states table
        if not inspector.has_table("oidc_states"):
            conn.execute(
                text("""
                CREATE TABLE oidc_states (
                    state TEXT PRIMARY KEY NOT NULL,
                    nonce TEXT NOT NULL,
                    redirect_uri TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL
                )
            """)
            )
            print("  ✓ Created oidc_states table")
        else:
            print("  → oidc_states table already exists")

        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_oidc_expires_at ON oidc_states(expires_at)")
        )
        print("  ✓ Ensured indexes on oidc_states")

        # Verify
        inspector = inspect(engine)
        tables = []
        for t in ["csrf_tokens", "oidc_states"]:
            if inspector.has_table(t):
                tables.append(t)

        print(f"\n✓ Security hardening migration completed: {', '.join(tables)}")


def downgrade(engine=None):
    """Remove security hardening tables (for testing/rollback only)."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        print("Rolling back security hardening migration...")
        conn.execute(text("DROP TABLE IF EXISTS csrf_tokens"))
        conn.execute(text("DROP TABLE IF EXISTS oidc_states"))
        print("✓ Security hardening migration rolled back")


if __name__ == "__main__":
    upgrade()

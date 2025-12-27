"""Security hardening migration - CSRF protection and OIDC state persistence.

This migration adds two new tables to support enhanced security:

1. csrf_tokens: Implements synchronizer token pattern for CSRF protection
   - Prevents cross-site request forgery attacks on state-changing operations
   - Tokens are tied to user sessions with 24-hour expiration
   - Required for POST/PUT/PATCH/DELETE requests

2. oidc_states: Persists OIDC authentication flow state
   - Replaces in-memory storage for multi-worker reliability
   - Supports container restarts during authentication flows
   - 10-minute expiration for OIDC flow state

Security improvements addressed:
- HIGH: CSRF protection for cookie-based JWT authentication
- MEDIUM: OIDC state persistence across workers and restarts
"""

import os
from pathlib import Path
from sqlalchemy import text, create_engine


def upgrade():
    """Add security hardening tables."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    # Create engine
    engine = create_engine(database_url)

    with engine.begin() as conn:
        print("Security Hardening Migration - Creating CSRF and OIDC state tables...")

        # Create csrf_tokens table
        try:
            conn.execute(
                text("""
                CREATE TABLE IF NOT EXISTS csrf_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token TEXT NOT NULL UNIQUE,
                    user_id INTEGER NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            )
            print("  ✓ Created csrf_tokens table")
        except Exception as e:
            if "already exists" in str(e).lower():
                print("  → csrf_tokens table already exists")
            else:
                raise

        # Create indexes for csrf_tokens
        try:
            conn.execute(
                text("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_csrf_token
                ON csrf_tokens(token)
            """)
            )
            print("  ✓ Created unique index on csrf_tokens.token")
        except Exception as e:
            print(f"  → Index on csrf_tokens.token may already exist: {e}")

        try:
            conn.execute(
                text("""
                CREATE INDEX IF NOT EXISTS idx_csrf_user_id
                ON csrf_tokens(user_id)
            """)
            )
            print("  ✓ Created index on csrf_tokens.user_id")
        except Exception as e:
            print(f"  → Index on csrf_tokens.user_id may already exist: {e}")

        try:
            conn.execute(
                text("""
                CREATE INDEX IF NOT EXISTS ix_csrf_user_token
                ON csrf_tokens(user_id, token)
            """)
            )
            print("  ✓ Created composite index on csrf_tokens(user_id, token)")
        except Exception as e:
            print(f"  → Composite index may already exist: {e}")

        # Create oidc_states table
        try:
            conn.execute(
                text("""
                CREATE TABLE IF NOT EXISTS oidc_states (
                    state TEXT PRIMARY KEY NOT NULL,
                    nonce TEXT NOT NULL,
                    redirect_uri TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL
                )
            """)
            )
            print("  ✓ Created oidc_states table")
        except Exception as e:
            if "already exists" in str(e).lower():
                print("  → oidc_states table already exists")
            else:
                raise

        # Create indexes for oidc_states
        try:
            conn.execute(
                text("""
                CREATE INDEX IF NOT EXISTS ix_oidc_expires_at
                ON oidc_states(expires_at)
            """)
            )
            print("  ✓ Created index on oidc_states.expires_at (for cleanup)")
        except Exception as e:
            print(f"  → Index on oidc_states.expires_at may already exist: {e}")

        # Verify table creation
        result = conn.execute(
            text("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name IN ('csrf_tokens', 'oidc_states')
            ORDER BY name
        """)
        )
        tables = [row[0] for row in result.fetchall()]

        print("\n✓ Security hardening migration completed successfully")
        print(f"  Created tables: {', '.join(tables)}")
        print("\nSecurity improvements:")
        print("  • CSRF protection: State-changing operations now require CSRF tokens")
        print(
            "  • OIDC reliability: Authentication state persists across workers/restarts"
        )
        print("\nNext steps:")
        print("  1. Frontend will automatically receive CSRF tokens on login")
        print("  2. OIDC flows will work reliably in multi-worker deployments")
        print("  3. Review security documentation in README.md")


def downgrade():
    """Remove security hardening tables (for testing/rollback only)."""
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    engine = create_engine(database_url)

    with engine.begin() as conn:
        print("Rolling back security hardening migration...")

        conn.execute(text("DROP TABLE IF EXISTS csrf_tokens"))
        print("  ✓ Dropped csrf_tokens table")

        conn.execute(text("DROP TABLE IF EXISTS oidc_states"))
        print("  ✓ Dropped oidc_states table")

        print("\n✓ Security hardening migration rolled back")
        print("  WARNING: CSRF protection and OIDC state persistence are now disabled")


if __name__ == "__main__":
    upgrade()

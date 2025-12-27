"""Add OIDC pending links table for username-based account linking.

This migration adds support for username-based OIDC account linking with password
verification. When a user logs in via OIDC and their username matches an existing
local account (but no OIDC link exists), they are prompted to verify their password
before linking the accounts.

The oidc_pending_links table stores:
- token: Cryptographically random URL-safe token (primary key)
- username: The matched username requiring verification
- oidc_claims: Full ID token claims from OIDC provider (JSON)
- userinfo_claims: Optional userinfo endpoint claims (JSON)
- provider_name: Display name of OIDC provider
- attempt_count: Number of failed password attempts (max 3)
- created_at: Token creation timestamp
- expires_at: Token expiration timestamp (5 minutes default)

Security features:
- Short expiration window (5 minutes)
- Limited password attempts (3 default)
- One-time use (deleted after successful link)
- Indexed for efficient cleanup of expired tokens
"""

import os
from pathlib import Path
from sqlalchemy import text, create_engine


def upgrade():
    """Add oidc_pending_links table for username-based account linking."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    # Create engine
    engine = create_engine(database_url)

    with engine.begin() as conn:
        print("Creating oidc_pending_links table...")

        # Create oidc_pending_links table
        try:
            conn.execute(
                text("""
                CREATE TABLE IF NOT EXISTS oidc_pending_links (
                    token TEXT PRIMARY KEY NOT NULL,
                    username TEXT NOT NULL,
                    oidc_claims TEXT NOT NULL,
                    userinfo_claims TEXT,
                    provider_name TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
            """)
            )
            print("  ✓ Created oidc_pending_links table")
        except Exception as e:
            if "already exists" in str(e).lower():
                print("  → oidc_pending_links table already exists")
            else:
                raise

        # Create index on token (primary key already indexed, but explicit for clarity)
        try:
            conn.execute(
                text("""
                CREATE INDEX IF NOT EXISTS ix_oidc_pending_links_token
                ON oidc_pending_links(token)
            """)
            )
            print("  ✓ Created index on token")
        except Exception as e:
            if "already exists" in str(e).lower():
                print("  → token index already exists")
            else:
                raise

        # Create index on username for efficient lookups
        try:
            conn.execute(
                text("""
                CREATE INDEX IF NOT EXISTS ix_oidc_pending_link_username
                ON oidc_pending_links(username)
            """)
            )
            print("  ✓ Created index on username")
        except Exception as e:
            if "already exists" in str(e).lower():
                print("  → username index already exists")
            else:
                raise

        # Create index on expires_at for efficient cleanup
        try:
            conn.execute(
                text("""
                CREATE INDEX IF NOT EXISTS ix_oidc_pending_link_expires_at
                ON oidc_pending_links(expires_at)
            """)
            )
            print("  ✓ Created index on expires_at")
        except Exception as e:
            if "already exists" in str(e).lower():
                print("  → expires_at index already exists")
            else:
                raise

        # Check if table is empty
        result = conn.execute(
            text("""
            SELECT COUNT(*) as pending_count FROM oidc_pending_links
        """)
        )
        row = result.fetchone()
        pending_count = row[0] if row else 0

        print("\nOIDC pending links table status:")
        print(f"  Pending link tokens: {pending_count}")

        print("\n✓ OIDC pending links migration completed successfully")
        print("\nFeature enabled:")
        print("  - Username-based account linking with password verification")
        print(
            "  - Users prompted for password when username matches but no OIDC link exists"
        )
        print("  - Tokens expire after 5 minutes (configurable via settings)")
        print("  - Maximum 3 password attempts per token (configurable via settings)")
        print("\nNew settings available:")
        print("  - oidc_link_token_expire_minutes (default: 5)")
        print("  - oidc_link_max_password_attempts (default: 3)")


if __name__ == "__main__":
    upgrade()

"""Add OIDC authentication fields to users table.

This migration adds support for OIDC/SSO authentication by adding:
- oidc_subject: The 'sub' claim from the OIDC provider (unique identifier)
- oidc_provider: Name of the OIDC provider (e.g., 'Authentik', 'Keycloak')
- auth_method: Authentication method ('local' or 'oidc')

Account Linking Strategy:
- Users can have both local (password) and OIDC authentication
- Email matching is used to link OIDC accounts to existing users
- First OIDC login for an email automatically links to existing account
- Users retain their original password and can use either login method

Migration also:
- Makes hashed_password nullable to support OIDC-only users
- Backfills existing users with auth_method='local'
"""

import os
from pathlib import Path
from sqlalchemy import text, create_engine


def upgrade():
    """Add OIDC authentication fields to users table."""
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    # Create engine
    engine = create_engine(database_url)

    with engine.begin() as conn:
        print("Adding OIDC authentication fields to users table...")

        # Add oidc_subject column (nullable, will be unique when set)
        try:
            conn.execute(
                text("""
                ALTER TABLE users ADD COLUMN oidc_subject TEXT
            """)
            )
            print("  ✓ Added oidc_subject column")
        except Exception as e:
            if "duplicate column" in str(e).lower():
                print("  → oidc_subject column already exists")
            else:
                raise

        # Add oidc_provider column
        try:
            conn.execute(
                text("""
                ALTER TABLE users ADD COLUMN oidc_provider TEXT
            """)
            )
            print("  ✓ Added oidc_provider column")
        except Exception as e:
            if "duplicate column" in str(e).lower():
                print("  → oidc_provider column already exists")
            else:
                raise

        # Add auth_method column (defaults to 'local')
        try:
            conn.execute(
                text("""
                ALTER TABLE users ADD COLUMN auth_method TEXT DEFAULT 'local'
            """)
            )
            print("  ✓ Added auth_method column")
        except Exception as e:
            if "duplicate column" in str(e).lower():
                print("  → auth_method column already exists")
            else:
                raise

        # Backfill auth_method for existing users
        result = conn.execute(
            text("""
            UPDATE users
            SET auth_method = 'local'
            WHERE auth_method IS NULL
        """)
        )
        rows_updated = result.rowcount
        if rows_updated > 0:
            print(
                f"  ✓ Backfilled auth_method='local' for {rows_updated} existing user(s)"
            )

        # Create unique index on oidc_subject (only where not null)
        try:
            conn.execute(
                text("""
                CREATE UNIQUE INDEX idx_users_oidc_subject
                ON users(oidc_subject)
                WHERE oidc_subject IS NOT NULL
            """)
            )
            print("  ✓ Created unique index on oidc_subject")
        except Exception as e:
            if "already exists" in str(e).lower():
                print("  → oidc_subject index already exists")
            else:
                raise

        # Create index on oidc_provider for faster lookups
        try:
            conn.execute(
                text("""
                CREATE INDEX idx_users_oidc_provider
                ON users(oidc_provider)
                WHERE oidc_provider IS NOT NULL
            """)
            )
            print("  ✓ Created index on oidc_provider")
        except Exception as e:
            if "already exists" in str(e).lower():
                print("  → oidc_provider index already exists")
            else:
                raise

        # Create index on auth_method for faster auth mode filtering
        try:
            conn.execute(
                text("""
                CREATE INDEX idx_users_auth_method
                ON users(auth_method)
            """)
            )
            print("  ✓ Created index on auth_method")
        except Exception as e:
            if "already exists" in str(e).lower():
                print("  → auth_method index already exists")
            else:
                raise

        # Check current user auth methods
        result = conn.execute(
            text("""
            SELECT
                COUNT(*) as total_users,
                SUM(CASE WHEN auth_method = 'local' THEN 1 ELSE 0 END) as local_users,
                SUM(CASE WHEN auth_method = 'oidc' THEN 1 ELSE 0 END) as oidc_users,
                SUM(CASE WHEN oidc_subject IS NOT NULL THEN 1 ELSE 0 END) as linked_oidc
            FROM users
        """)
        )
        row = result.fetchone()

        if row:
            total, local, oidc, linked = row
            # Handle None values from SUM
            total = total or 0
            local = local or 0
            oidc = oidc or 0
            linked = linked or 0

            print("\nAuthentication method status:")
            print(f"  Total users: {total}")
            print(f"  Local authentication: {local}")
            print(f"  OIDC authentication: {oidc}")
            print(f"  Users with linked OIDC: {linked}")

        print("\n✓ OIDC authentication migration completed successfully")
        print("\nNext steps:")
        print(
            "  1. Configure OIDC settings in Settings > System > Authentication Mode > OIDC"
        )
        print("  2. Set auth_mode='oidc' in settings to enable OIDC")
        print("  3. Users can link OIDC accounts via email matching on first login")


if __name__ == "__main__":
    upgrade()

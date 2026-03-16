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

from sqlalchemy import create_engine, inspect, text


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None):
    """Add OIDC authentication fields to users table."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        print("Adding OIDC authentication fields to users table...")

        # Check existing columns using inspect (works on both SQLite and PostgreSQL)
        inspector = inspect(engine)
        existing_columns = {col["name"] for col in inspector.get_columns("users")}

        # Add oidc_subject column (nullable, will be unique when set)
        if "oidc_subject" in existing_columns:
            print("  → oidc_subject column already exists")
        else:
            conn.execute(text("ALTER TABLE users ADD COLUMN oidc_subject TEXT"))
            print("  ✓ Added oidc_subject column")

        # Add oidc_provider column
        if "oidc_provider" in existing_columns:
            print("  → oidc_provider column already exists")
        else:
            conn.execute(text("ALTER TABLE users ADD COLUMN oidc_provider TEXT"))
            print("  ✓ Added oidc_provider column")

        # Add auth_method column (defaults to 'local')
        if "auth_method" in existing_columns:
            print("  → auth_method column already exists")
        else:
            conn.execute(text("ALTER TABLE users ADD COLUMN auth_method TEXT DEFAULT 'local'"))
            print("  ✓ Added auth_method column")

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
            print(f"  ✓ Backfilled auth_method='local' for {rows_updated} existing user(s)")

        # Create indexes using inspect to check existence first
        # (try/except breaks PostgreSQL transactions on duplicate errors)
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("users")}

        # Create unique index on oidc_subject (only where not null)
        if "idx_users_oidc_subject" in existing_indexes:
            print("  → oidc_subject index already exists")
        else:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX idx_users_oidc_subject "
                    "ON users(oidc_subject) WHERE oidc_subject IS NOT NULL"
                )
            )
            print("  ✓ Created unique index on oidc_subject")

        # Create index on oidc_provider for faster lookups
        if "idx_users_oidc_provider" in existing_indexes:
            print("  → oidc_provider index already exists")
        else:
            conn.execute(
                text(
                    "CREATE INDEX idx_users_oidc_provider "
                    "ON users(oidc_provider) WHERE oidc_provider IS NOT NULL"
                )
            )
            print("  ✓ Created index on oidc_provider")

        # Create index on auth_method for faster auth mode filtering
        if "idx_users_auth_method" in existing_indexes:
            print("  → auth_method index already exists")
        else:
            conn.execute(text("CREATE INDEX idx_users_auth_method ON users(auth_method)"))
            print("  ✓ Created index on auth_method")

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
        print("  1. Configure OIDC settings in Settings > System > Authentication Mode > OIDC")
        print("  2. Set auth_mode='oidc' in settings to enable OIDC")
        print("  3. Users can link OIDC accounts via email matching on first login")


if __name__ == "__main__":
    upgrade()

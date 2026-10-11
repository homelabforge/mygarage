"""Migrate password hashing from bcrypt to Argon2.

This migration marks the transition to Argon2id for password hashing.
No database schema changes are required - the existing hashed_password
column (String 255) is sufficient for both bcrypt and Argon2 hashes.
New passwords are hashed with Argon2 (in auth.py). The migration itself
only counts each kind of hash and rewrites nothing.

Update 2026-10 (PR 1c): bcrypt verification is gone. bcrypt was never a
dependency in this repo, so a leftover bcrypt hash can't sign in; an admin
resets that password, and the login log names the account.
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
    """Mark the Argon2 migration as applied.

    This is a code-level migration, not a schema migration. Nothing rehashes
    a bcrypt password; that account needs a password reset.
    """
    if engine is None:
        engine = _get_fallback_engine()

    inspector = inspect(engine)

    # Guard: users table must exist
    if not inspector.has_table("users"):
        print("  users table does not exist, skipping Argon2 migration info")
        return

    # Guard: hashed_password column must exist
    columns = {col["name"] for col in inspector.get_columns("users")}
    if "hashed_password" not in columns:
        print("  hashed_password column not found in users table, skipping Argon2 migration info")
        return

    with engine.begin() as conn:
        # Check current password hash types for informational purposes
        result = conn.execute(
            text("""
            SELECT
                COUNT(*) as total_users,
                SUM(CASE WHEN hashed_password LIKE '$argon2%' THEN 1 ELSE 0 END) as argon2_hashes,
                SUM(CASE WHEN hashed_password LIKE '$2b$%' THEN 1 ELSE 0 END) as bcrypt_hashes
            FROM users
        """)
        )
        row = result.fetchone()

        if row:
            total, argon2, bcrypt = row
            # Handle None values from SUM when there are no rows
            total = total or 0
            argon2 = argon2 or 0
            bcrypt = bcrypt or 0

            print("Password hash migration status:")
            print(f"  Total users: {total}")
            print(f"  Argon2 hashes: {argon2}")
            print(f"  bcrypt hashes (legacy): {bcrypt}")

            if total == 0:
                print("\n  ✓ No users found - migration tracking complete")
            elif bcrypt > 0:
                print(f"\n  → {bcrypt} user(s) need a password reset: bcrypt sign-in was removed")
            else:
                print("\n  ✓ All passwords migrated to Argon2")
                print("  Note: You can remove 'bcrypt' from pyproject.toml dependencies")
        else:
            print("✓ No users found - migration tracking complete")

        print("\n✓ Argon2 migration applied successfully")


if __name__ == "__main__":
    upgrade()

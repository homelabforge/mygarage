"""Migrate password hashing from bcrypt to Argon2.

This migration marks the transition to Argon2id for password hashing.
No database schema changes are required - the existing hashed_password
column (String 255) is sufficient for both bcrypt and Argon2 hashes.

Migration strategy:
- New passwords are hashed with Argon2 (in auth.py)
- Existing bcrypt passwords are verified via hybrid verification
- Passwords are auto-rehashed to Argon2 on successful login
- Both hash types are supported during the transition period

After all users have logged in and passwords are migrated, the bcrypt
dependency can be removed from pyproject.toml.
"""

import os
from pathlib import Path
from sqlalchemy import text, create_engine


def upgrade():
    """Mark the Argon2 migration as applied.

    This is a code-level migration, not a schema migration.
    The actual password rehashing happens automatically in auth.py
    when users log in.
    """
    # Get database path from environment
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    database_path = data_dir / "mygarage.db"
    database_url = f"sqlite:///{database_path}"

    # Create engine
    engine = create_engine(database_url)

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
                print(
                    f"\n  → {bcrypt} user(s) will auto-migrate to Argon2 on next login"
                )
            else:
                print("\n  ✓ All passwords migrated to Argon2")
                print(
                    "  Note: You can remove 'bcrypt' from pyproject.toml dependencies"
                )
        else:
            print("✓ No users found - migration tracking complete")

        print("\n✓ Argon2 migration applied successfully")


if __name__ == "__main__":
    upgrade()

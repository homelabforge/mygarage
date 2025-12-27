#!/usr/bin/env python3
"""Wrapper to run unlink_oidc from the /app/app directory."""

import subprocess
import sys

# Run the script from the correct directory
result = subprocess.run(
    [
        "python3",
        "-c",
        """
import sys
sys.path.insert(0, '/app/app')
import asyncio
from database import AsyncSessionLocal
from models.user import User
from sqlalchemy import select

async def unlink_oidc_account(username: str):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()

        if not user:
            print(f"❌ User '{username}' not found")
            return False

        if not user.oidc_subject:
            print(f"ℹ️  User '{username}' has no OIDC link")
            return False

        old_subject = user.oidc_subject
        user.oidc_subject = None
        await db.commit()

        print(f"✅ Unlinked OIDC from user '{username}'")
        print(f"   Old oidc_subject: {old_subject}")
        print(f"   Email: {user.email}")
        print(f"   Has password: {bool(user.hashed_password)}")
        return True

username = sys.argv[1] if len(sys.argv) > 1 else "oaniach1"
asyncio.run(unlink_oidc_account(username))
""",
    ]
    + sys.argv[1:],
    cwd="/app/app",
)

sys.exit(result.returncode)

"""Tokens the browser holds and the database only keeps a digest of.

CSRF tokens and pending SSO links are handed out once in plaintext and stored
as their SHA-256 hex digest, so someone who can read the database (a backup, a
stray copy of the file) can't replay what's in it. Every lookup hashes what it
was given and compares digests.

They come from ``secrets.token_urlsafe(48)``, 384 random bits, so a plain
SHA-256 is enough. A slow password hash buys nothing against a space nobody
can search (same reasoning as ``widget_auth``).
"""

import hashlib
import secrets

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.csrf_token import CSRFToken
from app.utils.datetime_utils import utc_now

#: Random bytes per token; 48 bytes is 64 URL-safe characters.
TOKEN_BYTES = 48


def hash_token(token: str) -> str:
    """Return the SHA-256 hex digest of a random token, the form the database keeps."""
    # codeql[py/weak-sensitive-data-hashing] - 384-bit random token, not a password; see module docstring.
    return hashlib.sha256(token.encode()).hexdigest()


async def issue_csrf_token(db: AsyncSession, user_id: int) -> str:
    """Store a new CSRF token for this user and return the plaintext.

    Clears the user's expired tokens first. Doesn't commit: the caller's
    commit carries it, so login's last_login and the token land together.
    """
    await db.execute(
        delete(CSRFToken).where(
            CSRFToken.user_id == user_id,
            CSRFToken.expires_at <= utc_now(),
        )
    )
    token = secrets.token_urlsafe(TOKEN_BYTES)
    db.add(
        CSRFToken(
            token=hash_token(token),
            user_id=user_id,
            expires_at=CSRFToken.get_expiry_time(),
        )
    )
    return token

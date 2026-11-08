"""The check that a CSRF token was stored as a digest and still works.

The suite runs with the CSRF middleware off, so these need the
``csrf_enforced`` fixture in ``tests/integration/conftest.py``. The digest is
computed here with hashlib, never through the app's helper, so a helper that
hashed the wrong thing would still fail.
"""

import hashlib

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.csrf_token import CSRFToken

#: What the middleware says to a token it can't find.
REJECTED = "Invalid or expired CSRF token. Please login again."


def sha256_hex(token: str) -> str:
    """The SHA-256 hex digest of a token, as the database should hold it."""
    return hashlib.sha256(token.encode()).hexdigest()


async def stored_csrf_tokens(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int
) -> set[str]:
    """Every csrf_tokens.token on file for this user, read over a fresh session."""
    async with sessionmaker() as fresh:
        rows = await fresh.execute(select(CSRFToken.token).where(CSRFToken.user_id == user_id))
        return set(rows.scalars())


async def assert_csrf_hashed_and_enforced(
    client: AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    user_id: int,
    issued: str,
) -> None:
    """The row holds the issued token's digest, the token passes a write, the digest doesn't.

    The client must already carry the user's session cookie. ``PUT
    /api/auth/me`` with an empty body is the write: it changes nothing but
    ``updated_at``, and it isn't on the middleware's exempt list.
    """
    digest = sha256_hex(issued)
    stored = await stored_csrf_tokens(sessionmaker, user_id)
    assert digest in stored, "the issued token's digest isn't on file"
    assert issued not in stored, "the plaintext token was stored"

    accepted = await client.put("/api/auth/me", json={}, headers={"X-CSRF-Token": issued})
    assert accepted.status_code == 200, accepted.text

    refused = await client.put("/api/auth/me", json={}, headers={"X-CSRF-Token": digest})
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == REJECTED

"""CSRF tokens are kept as SHA-256 digests, so a database read can't be replayed as a token.

Login and the refresh endpoint hand out the plaintext once and store only its
digest. The middleware hashes what a write presents and looks that up, so the
issued token passes and the stored digest is refused. These run the real
middleware (``csrf_enforced``). The SSO callback and the link step are covered
in ``routes/test_oidc_callback_and_link.py``.
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.csrf_token import CSRFToken
from app.services.hashed_tokens import hash_token
from tests.integration._csrf import assert_csrf_hashed_and_enforced, sha256_hex

pytestmark = [pytest.mark.integration]


@pytest_asyncio.fixture
async def issued(db_session: AsyncSession) -> AsyncIterator[list[str]]:
    """Collects the CSRF tokens a test is handed, and deletes their rows afterwards."""
    tokens: list[str] = []
    yield tokens
    await db_session.rollback()
    digests = [sha256_hex(t) for t in tokens]
    await db_session.execute(delete(CSRFToken).where(CSRFToken.token.in_(digests)))
    await db_session.commit()


async def _login(client: AsyncClient, test_user: dict[str, object], issued: list[str]) -> str:
    response = await client.post(
        "/api/auth/login",
        json={"username": test_user["username"], "password": "testpassword123"},
    )
    assert response.status_code == 200, response.text
    token = response.json()["csrf_token"]
    issued.append(token)
    return token


def test_hash_token_is_the_sha256_hex_digest() -> None:
    # The FIPS 180-2 "abc" vector, so a helper that hashed something else fails here.
    assert hash_token("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


@pytest.mark.usefixtures("csrf_enforced")
async def test_login_stores_the_digest_and_the_token_still_works(
    client: AsyncClient,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    test_user: dict[str, object],
    issued: list[str],
) -> None:
    token = await _login(client, test_user, issued)

    await assert_csrf_hashed_and_enforced(client, test_sessionmaker, int(test_user["id"]), token)


@pytest.mark.usefixtures("csrf_enforced")
async def test_refresh_stores_the_digest_and_the_token_still_works(
    client: AsyncClient,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    test_user: dict[str, object],
    issued: list[str],
) -> None:
    await _login(client, test_user, issued)

    response = await client.get("/api/auth/csrf-token")
    assert response.status_code == 200, response.text
    token = response.json()["csrf_token"]
    assert token is not None
    issued.append(token)

    await assert_csrf_hashed_and_enforced(client, test_sessionmaker, int(test_user["id"]), token)

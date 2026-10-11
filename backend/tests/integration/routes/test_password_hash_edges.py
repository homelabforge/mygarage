"""Stored password values the hasher can't read: a miss or a 400, never a 500.

A damaged $argon2 row raised VerificationError straight out of verify_password,
and an SSO-only account (no hash at all) hit None.startswith on change-password.
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.auth import create_access_token

pytestmark = [pytest.mark.integration, pytest.mark.auth, pytest.mark.asyncio]

_UNREADABLE = "c1_route_unreadable"
_SSO = "c1_route_sso_only"

# Fixed values so the node ids stay put. bad-base64 is conftest's hash of
# testpassword123 with its tail swapped for junk.
UNREADABLE_HASHES = {
    "truncated": "$argon2id$v=19$m=102400,t=2,p=8$c2FsdHNhbHQ",
    "bcrypt": "$2b$12$K9v3M5qVxPZYH.fQz9J9/.kN7xN8YE9Xw5qKjN8QrXj9zKzN8QrX.",
    "garbage-after-tag": "$argon2id$garbage",
    "bad-base64": (
        "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7S!!!!!"
    ),
    "unknown-type-tag": "$argon2zz$v=19$m=1,t=1,p=1$abc$def",
    "non-ascii": "$argon2id$v=19$m=102400,t=2,p=8$é",
}


@pytest.fixture(autouse=True)
def _reset_rate_limits() -> None:
    """Login and change-password are limited per address; an earlier suite can use it up."""
    from app.routes.auth import limiter as auth_limiter

    storage = auth_limiter._storage
    storage.storage.clear()
    storage.expirations.clear()
    if hasattr(storage, "events"):
        storage.events.clear()


@pytest_asyncio.fixture(params=list(UNREADABLE_HASHES))
async def unreadable_user(request, db_session: AsyncSession) -> AsyncGenerator[User]:
    """A password account whose stored hash Argon2 can't read (pre-Argon2 or damaged)."""
    await db_session.execute(delete(User).where(User.username == _UNREADABLE))
    user = User(
        username=_UNREADABLE,
        email=f"{_UNREADABLE}@example.com",
        hashed_password=UNREADABLE_HASHES[request.param],
        auth_method="local",
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.commit()
    yield user
    await db_session.execute(delete(User).where(User.username == _UNREADABLE))
    await db_session.commit()


@pytest_asyncio.fixture
async def sso_only_user(db_session: AsyncSession) -> AsyncGenerator[User]:
    """An SSO account with no password."""
    await db_session.execute(delete(User).where(User.username == _SSO))
    user = User(
        username=_SSO,
        email=f"{_SSO}@example.com",
        hashed_password=None,
        auth_method="oidc",
        oidc_subject="c1-sub",
        oidc_provider="c1-idp",
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.commit()
    yield user
    await db_session.execute(delete(User).where(User.username == _SSO))
    await db_session.commit()


async def test_login_with_an_unreadable_hash_is_a_401(
    client: AsyncClient, unreadable_user: User, set_auth_mode
) -> None:
    await set_auth_mode("local")
    response = await client.post(
        "/api/auth/login", json={"username": _UNREADABLE, "password": "Whatever-password1"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect username or password"


async def test_login_as_an_sso_only_account_is_a_401(
    client: AsyncClient, sso_only_user: User, set_auth_mode
) -> None:
    """The None case: no hash at all is the same plain miss."""
    await set_auth_mode("local")
    response = await client.post(
        "/api/auth/login", json={"username": _SSO, "password": "Whatever-password1"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect username or password"


async def test_sso_only_account_cannot_change_a_password_it_does_not_have(
    client: AsyncClient, sso_only_user: User, set_auth_mode
) -> None:
    await set_auth_mode("local")
    token = create_access_token(data={"sub": str(sso_only_user.id), "username": _SSO})
    response = await client.put(
        "/api/auth/me/password",
        json={"current_password": "anything", "new_password": "NewPassword123!"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "This account signs in through SSO and has no password to change"
    )

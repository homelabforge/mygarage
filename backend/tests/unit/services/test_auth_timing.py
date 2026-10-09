"""A login that can't succeed still pays for one Argon2 verify (A-14).

An unknown username and an SSO-only account used to return before any hash
work, while a real password account paid for a full verify. So the response
time told you which usernames exist.
"""

from collections.abc import AsyncGenerator, Generator
from unittest import mock

import argon2
import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services import auth
from app.services.auth import authenticate_user

_OIDC_USERNAME = "a14_oidc_only"


@pytest.fixture
def argon2_verify() -> Generator[mock.MagicMock]:
    """Spy on Argon2's verify, still running the real one.

    Patched at the class: PasswordHasher has __slots__, so `auth.ph.verify`
    can't be patched on the instance.
    """
    with mock.patch.object(
        argon2.PasswordHasher, "verify", autospec=True, side_effect=argon2.PasswordHasher.verify
    ) as spy:
        yield spy


@pytest_asyncio.fixture
async def oidc_only_user(db_session: AsyncSession) -> AsyncGenerator[User]:
    """An SSO account with no password, removed afterwards (the suite shares one DB)."""
    await db_session.execute(delete(User).where(User.username == _OIDC_USERNAME))
    user = User(
        username=_OIDC_USERNAME,
        email=f"{_OIDC_USERNAME}@example.com",
        hashed_password=None,
        auth_method="oidc",
        oidc_subject="a14-sub",
        oidc_provider="a14-idp",
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.commit()
    yield user
    await db_session.execute(delete(User).where(User.username == _OIDC_USERNAME))
    await db_session.commit()


def _verified_hashes(spy: mock.MagicMock) -> list[str]:
    """The hash each verify ran against. autospec hands the spy `self` first."""
    return [call.args[1] for call in spy.call_args_list]


def _assert_one_full_cost_verify(spy: mock.MagicMock) -> None:
    """Exactly one verify, against a hash at the live cost.

    A cheaper dummy hash would still be a call, and still leak the timing.
    """
    hashes = _verified_hashes(spy)
    assert len(hashes) == 1
    assert not auth.ph.check_needs_rehash(hashes[0])


@pytest.mark.unit
@pytest.mark.auth
async def test_unknown_username_runs_one_argon2_verify(
    db_session: AsyncSession, argon2_verify: mock.MagicMock
) -> None:
    """No such user: same Argon2 work as a wrong password, still no user back."""
    result = await authenticate_user(db_session, "a14_no_such_user", "whatever-password")

    assert result is None
    _assert_one_full_cost_verify(argon2_verify)


@pytest.mark.unit
@pytest.mark.auth
async def test_oidc_only_user_runs_one_argon2_verify(
    db_session: AsyncSession, oidc_only_user: User, argon2_verify: mock.MagicMock
) -> None:
    """SSO-only account: still refused, but only after the same Argon2 work."""
    result = await authenticate_user(db_session, oidc_only_user.username, "whatever-password")

    assert result is None
    _assert_one_full_cost_verify(argon2_verify)


@pytest.mark.unit
@pytest.mark.auth
async def test_known_user_right_password_still_logs_in(
    db_session: AsyncSession, test_user: dict[str, object], argon2_verify: mock.MagicMock
) -> None:
    """Control: a real password login is one verify and gets the user, as before."""
    result = await authenticate_user(db_session, "testuser", "testpassword123")

    assert result is not None
    assert result.id == test_user["id"]
    assert argon2_verify.call_count == 1

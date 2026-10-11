"""A login that can't succeed still pays for one Argon2 verify (A-14).

An unknown username, an SSO-only account and a legacy bcrypt account used to
return before any Argon2 work, while a real password account paid for a full
verify. So the response time told you which usernames exist.
"""

import logging
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
_BCRYPT_USERNAME = "a14_legacy_bcrypt"


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


@pytest_asyncio.fixture
async def legacy_bcrypt_user(db_session: AsyncSession) -> AsyncGenerator[User]:
    """A password account still on a pre-Argon2 bcrypt hash, removed afterwards."""
    await db_session.execute(delete(User).where(User.username == _BCRYPT_USERNAME))
    user = User(
        username=_BCRYPT_USERNAME,
        email=f"{_BCRYPT_USERNAME}@example.com",
        hashed_password="$2b$12$K9v3M5qVxPZYH.fQz9J9/.kN7xN8YE9Xw5qKjN8QrXj9zKzN8QrX.",
        auth_method="local",
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.commit()
    yield user
    await db_session.execute(delete(User).where(User.username == _BCRYPT_USERNAME))
    await db_session.commit()


_DAMAGED_USERNAME = "c1_damaged_hash"

# A real live-cost hash, cut or corrupted. Each fails before Argon2 does any work.
_GOOD = auth.ph.hash("irrelevant")
DAMAGED_HASHES = {
    "truncated": _GOOD[:40],
    "garbage-after-tag": "$argon2id$garbage",
    "bad-base64": _GOOD[:-5] + "!!!!!",
    "unknown-type-tag": "$argon2zz$v=19$m=1,t=1,p=1$abc$def",
    "non-ascii": "$argon2id$v=19$m=102400,t=2,p=8$é",
}


@pytest_asyncio.fixture(params=sorted(DAMAGED_HASHES))
async def damaged_hash_user(
    request: pytest.FixtureRequest, db_session: AsyncSession
) -> AsyncGenerator[User]:
    """A password account whose stored hash is damaged, removed afterwards."""
    await db_session.execute(delete(User).where(User.username == _DAMAGED_USERNAME))
    user = User(
        username=_DAMAGED_USERNAME,
        email=f"{_DAMAGED_USERNAME}@example.com",
        hashed_password=DAMAGED_HASHES[request.param],
        auth_method="local",
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.commit()
    yield user
    await db_session.execute(delete(User).where(User.username == _DAMAGED_USERNAME))
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
@pytest.mark.parametrize("password", ["wrong-password", "x" * 73], ids=["wrong", "over-72-bytes"])
async def test_legacy_bcrypt_miss_runs_one_argon2_verify(
    db_session: AsyncSession,
    legacy_bcrypt_user: User,
    argon2_verify: mock.MagicMock,
    password: str,
) -> None:
    """A bcrypt hash is no hash Argon2 can read: a miss that pays the dummy like the rest."""
    result = await authenticate_user(db_session, legacy_bcrypt_user.username, password)

    assert result is None
    _assert_one_full_cost_verify(argon2_verify)


@pytest.mark.unit
@pytest.mark.auth
async def test_known_user_wrong_password_runs_one_argon2_verify(
    db_session: AsyncSession, test_user: dict[str, object], argon2_verify: mock.MagicMock
) -> None:
    """Control: an Argon2 miss already paid for its own verify, so no dummy on top."""
    result = await authenticate_user(db_session, "testuser", "wrong-password")

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


@pytest.mark.unit
@pytest.mark.auth
async def test_damaged_hash_is_a_miss_that_pays_the_dummy(
    db_session: AsyncSession, damaged_hash_user: User, argon2_verify: mock.MagicMock
) -> None:
    """A damaged row used to raise out of verify (a 500), or skip the dummy."""
    result = await authenticate_user(db_session, damaged_hash_user.username, "whatever-password")

    assert result is None
    assert _verified_hashes(argon2_verify).count(auth._DUMMY_HASH) == 1


@pytest.mark.unit
@pytest.mark.auth
@pytest.mark.parametrize(
    "stored",
    [None, "$2b$12$abc", *DAMAGED_HASHES.values()],
    ids=["none", "bcrypt", *DAMAGED_HASHES],
)
def test_verify_password_never_raises(stored: str | None) -> None:
    """Every caller (login, change password, SSO linking) gets a plain False."""
    assert auth.verify_password("whatever-password", stored) is False


@pytest.mark.unit
@pytest.mark.auth
async def test_damaged_hash_logs_a_reset_hint(
    db_session: AsyncSession, damaged_hash_user: User, caplog: pytest.LogCaptureFixture
) -> None:
    """An admin needs to know this account can't sign in until its password is reset."""
    caplog.set_level(logging.WARNING, logger="app.services.auth")
    await authenticate_user(db_session, damaged_hash_user.username, "whatever-password")

    lines = [r.getMessage() for r in caplog.records if "can't be read as Argon2" in r.getMessage()]
    assert lines == [
        f"Password hash for {_DAMAGED_USERNAME} can't be read as Argon2 "
        "(pre-Argon2 or damaged); an admin has to reset this password"
    ]

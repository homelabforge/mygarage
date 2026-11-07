"""An SSO email match used to link into the matching account with no password.

That was an account takeover three ways: an IdP that lets users set an unverified
email, a local user setting their email to a colleague's unused address, and a
second IdP identity with the same email overwriting the first one's link.

Now an email match only picks which account to offer. A password account goes to
the password-link page for its own username; everything else is refused. Every
refusal leaves the matched row alone, in memory and in the database.

The one exception is a relink an admin armed on the account: until it expires,
the next email or username match links it and spends the arm. Using one is
audited, and any SSO sign-in that already works cancels it.
"""

import datetime as dt
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.exceptions import OIDCLoginRefusedError, PendingLinkRequiredError
from app.models.audit_log import AuditLog
from app.models.settings import Setting
from app.models.user import User
from app.services.oidc import (
    create_or_update_user_from_oidc,
    create_pending_link_token,
    validate_and_consume_pending_link,
)
from app.utils.datetime_utils import utc_now
from tests.integration._oidc_refusals import (
    CODES,
    DISABLED,
    EMAIL_LINKED_ELSEWHERE,
    EMAIL_NO_PASSWORD,
    NO_ACCOUNT,
    USERNAME_LINKED_ELSEWHERE,
    USERNAME_NO_PASSWORD,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# argon2id of "testpassword123", as in tests/conftest.py.
_HASH = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
_LAST_LOGIN = dt.datetime(2024, 1, 2, 3, 4, 5)
_WATCHED = ("oidc_subject", "oidc_provider", "auth_method", "last_login", "full_name")
_RELINK_USED = "oidc_relink_used"


@pytest_asyncio.fixture(autouse=True)
async def _oidc_rows(db_session: AsyncSession):
    """Start with no oidc_* settings and put the originals back afterwards."""
    rows = (await db_session.execute(select(Setting).where(Setting.key.like("oidc_%")))).scalars()
    saved = [(r.key, r.value, r.category, r.description, r.encrypted) for r in rows]
    await db_session.execute(delete(Setting).where(Setting.key.like("oidc_%")))
    await db_session.commit()
    yield
    await db_session.rollback()
    await db_session.execute(delete(Setting).where(Setting.key.like("oidc_%")))
    for key, value, category, description, encrypted in saved:
        db_session.add(
            Setting(
                key=key,
                value=value,
                category=category,
                description=description,
                encrypted=encrypted,
            )
        )
    await db_session.commit()


@pytest_asyncio.fixture
async def made_users(db_session: AsyncSession):
    """Collects users a test creates and deletes them, and their link audit rows, afterwards."""
    ids: list[int] = []
    yield ids
    await db_session.rollback()
    await db_session.execute(
        delete(AuditLog).where(
            AuditLog.action.in_((_RELINK_USED, "oidc_account_linked")), AuditLog.user_id.in_(ids)
        )
    )
    for user_id in ids:
        user = await db_session.get(User, user_id)
        if user is not None:
            await db_session.delete(user)
    await db_session.commit()


async def _account(
    db_session: AsyncSession,
    made_users: list[int],
    *,
    password: bool = True,
    subject: str | None = None,
    active: bool = True,
    relink_until: dt.datetime | None = None,
) -> User:
    """A MyGarage account with a fixed past last_login, so any write to it shows."""
    tag = uuid.uuid4().hex[:10]
    user = User(
        username=f"acct_{tag}",
        email=f"acct_{tag}@example.com",
        hashed_password=_HASH if password else None,
        full_name="Original Name",
        is_active=active,
        is_admin=False,
        oidc_subject=subject,
        oidc_provider="Old IdP" if subject else None,
        auth_method="oidc" if subject else "local",
        last_login=_LAST_LOGIN,
        oidc_relink_until=relink_until,
    )
    db_session.add(user)
    await db_session.commit()
    made_users.append(user.id)
    return user


def _claims(
    *, sub: str | None = None, email: str | None = None, username: str | None = None, **extra: Any
) -> dict[str, Any]:
    """ID token claims; anything not given is unique, so it matches nothing."""
    tag = uuid.uuid4().hex[:10]
    return {
        "sub": sub or f"sub-{tag}",
        "email": email or f"sso_{tag}@example.com",
        "preferred_username": username or f"sso_{tag}",
        "name": "Claimed Name",
        **extra,
    }


async def _login(db_session: AsyncSession, claims: dict[str, Any]) -> object:
    """Run the SSO resolution and hand back what came out: a user, a refusal or a pending link.

    Anything else raised is a bug, so it escapes and the test errors on it.
    """
    try:
        return await create_or_update_user_from_oidc(db_session, claims, None, {})
    except (OIDCLoginRefusedError, PendingLinkRequiredError) as exc:
        return exc


def _snapshot(user: User) -> dict[str, Any]:
    return {field: getattr(user, field) for field in _WATCHED}


async def _assert_untouched(db_session: AsyncSession, user: User, before: dict[str, Any]) -> None:
    """The row is unchanged in memory, then again after a flush and a re-read."""
    assert _snapshot(user) == before, "the matched row changed in memory"
    # autoflush is off, so a bare refresh() would throw away a pending change.
    await db_session.flush()
    await db_session.refresh(user)
    assert _snapshot(user) == before, "the matched row changed in the database"


def _assert_refused(
    outcome: object,
    message: str,
    username: str | None,
    details: dict[str, Any] | None = None,
) -> None:
    """A refusal with this message and code, and no audit details unless they're given."""
    assert isinstance(outcome, OIDCLoginRefusedError), f"expected a refusal, got {outcome!r}"
    assert outcome.message == message
    assert outcome.code == CODES[message]
    assert outcome.username == username
    assert outcome.details == details


# 0. The helper every test here goes through hands back the two outcomes, nothing else.
async def test_login_lets_an_unexpected_error_through(db_session: AsyncSession):
    """A bug in the service has to fail loudly, not come back as an outcome to compare."""
    with (
        patch(
            f"{__name__}.create_or_update_user_from_oidc",
            new_callable=AsyncMock,
            side_effect=RuntimeError("not an outcome"),
        ),
        pytest.raises(RuntimeError, match="not an outcome"),
    ):
        await _login(db_session, _claims())


# 1. Email matches a password account: the password page, for that account.
async def test_email_match_with_password_goes_to_that_accounts_password_page(
    db_session: AsyncSession, made_users: list[int]
):
    account = await _account(db_session, made_users)
    before = _snapshot(account)
    claims = _claims(email=account.email)
    assert claims["preferred_username"] != account.username

    outcome = await _login(db_session, claims)

    await _assert_untouched(db_session, account, before)
    assert isinstance(outcome, PendingLinkRequiredError), f"got {outcome!r}"
    assert outcome.username == account.username
    assert outcome.claims == claims


# 2. Email matches an account linked to another subject: refused, old link kept.
@pytest.mark.parametrize("password", [True, False], ids=["with-password", "sso-only"])
async def test_email_match_linked_elsewhere_is_refused(
    db_session: AsyncSession, made_users: list[int], password: bool
):
    old_sub = f"old-{uuid.uuid4().hex[:10]}"
    account = await _account(db_session, made_users, password=password, subject=old_sub)
    before = _snapshot(account)

    outcome = await _login(db_session, _claims(email=account.email))

    await _assert_untouched(db_session, account, before)
    assert account.oidc_subject == old_sub
    _assert_refused(outcome, EMAIL_LINKED_ELSEWHERE, account.username)


# 3. Email matches an account with no password and no link: nothing to prove it with.
async def test_email_match_without_password_is_refused(
    db_session: AsyncSession, made_users: list[int]
):
    account = await _account(db_session, made_users, password=False)
    before = _snapshot(account)

    outcome = await _login(db_session, _claims(email=account.email))

    await _assert_untouched(db_session, account, before)
    _assert_refused(outcome, EMAIL_NO_PASSWORD, account.username)


# 4. Email matches an inactive account: disabled wins over every other state.
@pytest.mark.parametrize(
    ("password", "linked"),
    [(True, False), (False, False), (True, True)],
    ids=["with-password", "no-password", "linked-elsewhere"],
)
async def test_email_match_on_inactive_account_is_refused_as_disabled(
    db_session: AsyncSession, made_users: list[int], password: bool, linked: bool
):
    subject = f"old-{uuid.uuid4().hex[:10]}" if linked else None
    account = await _account(
        db_session, made_users, password=password, subject=subject, active=False
    )
    before = _snapshot(account)

    outcome = await _login(db_session, _claims(email=account.email))

    await _assert_untouched(db_session, account, before)
    _assert_refused(outcome, DISABLED, account.username)


# 5. email_verified is never read: case 1 again, same answer either way.
@pytest.mark.parametrize("verified", [True, False])
async def test_email_verified_changes_nothing(
    db_session: AsyncSession, made_users: list[int], verified: bool
):
    account = await _account(db_session, made_users)
    before = _snapshot(account)

    outcome = await _login(db_session, _claims(email=account.email, email_verified=verified))

    await _assert_untouched(db_session, account, before)
    assert isinstance(outcome, PendingLinkRequiredError), f"got {outcome!r}"
    assert outcome.username == account.username


# 6. Subject matches an inactive user: refused before last_login is touched.
async def test_subject_match_on_inactive_user_is_refused(
    db_session: AsyncSession, made_users: list[int]
):
    sub = f"sub-{uuid.uuid4().hex[:10]}"
    account = await _account(db_session, made_users, subject=sub, active=False)
    before = _snapshot(account)

    outcome = await _login(db_session, _claims(sub=sub))

    await _assert_untouched(db_session, account, before)
    _assert_refused(outcome, DISABLED, account.username)


async def test_subject_match_on_active_user_still_logs_in(
    db_session: AsyncSession, made_users: list[int]
):
    """Guard: the normal SSO login still refreshes the row."""
    sub = f"sub-{uuid.uuid4().hex[:10]}"
    account = await _account(db_session, made_users, subject=sub)

    outcome = await _login(db_session, _claims(sub=sub))

    assert outcome is account
    assert account.oidc_subject == sub
    assert account.full_name == "Claimed Name"
    assert account.oidc_provider == "OIDC Provider"
    assert account.last_login is not None and account.last_login > _LAST_LOGIN


# 7. The username step: its two conflicts and an inactive account are refusals.
async def test_username_match_sso_only_is_refused(db_session: AsyncSession, made_users: list[int]):
    account = await _account(db_session, made_users, password=False)
    before = _snapshot(account)

    outcome = await _login(db_session, _claims(username=account.username))

    await _assert_untouched(db_session, account, before)
    _assert_refused(outcome, USERNAME_NO_PASSWORD, account.username)


async def test_username_match_linked_elsewhere_is_refused(
    db_session: AsyncSession, made_users: list[int]
):
    old_sub = f"old-{uuid.uuid4().hex[:10]}"
    account = await _account(db_session, made_users, subject=old_sub)
    before = _snapshot(account)

    outcome = await _login(db_session, _claims(username=account.username))

    await _assert_untouched(db_session, account, before)
    _assert_refused(outcome, USERNAME_LINKED_ELSEWHERE, account.username)


@pytest.mark.parametrize("password", [True, False], ids=["with-password", "sso-only"])
async def test_username_match_on_inactive_account_is_refused_as_disabled(
    db_session: AsyncSession, made_users: list[int], password: bool
):
    account = await _account(db_session, made_users, password=password, active=False)
    before = _snapshot(account)

    outcome = await _login(db_session, _claims(username=account.username))

    await _assert_untouched(db_session, account, before)
    _assert_refused(outcome, DISABLED, account.username)


async def test_clean_username_match_still_goes_to_password_page(
    db_session: AsyncSession, made_users: list[int]
):
    """Guard: an active, unlinked password account matched by username is unchanged."""
    account = await _account(db_session, made_users)
    before = _snapshot(account)

    outcome = await _login(db_session, _claims(username=account.username))

    await _assert_untouched(db_session, account, before)
    assert isinstance(outcome, PendingLinkRequiredError), f"got {outcome!r}"
    assert outcome.username == account.username


# 7b. When both steps could answer, the email step goes first.
async def test_email_match_beats_a_username_match_on_another_account(
    db_session: AsyncSession, made_users: list[int]
):
    """Guard: two password accounts, one per claim. The password page is the email one's."""
    by_email = await _account(db_session, made_users)
    by_username = await _account(db_session, made_users)
    email_before, username_before = _snapshot(by_email), _snapshot(by_username)

    outcome = await _login(db_session, _claims(email=by_email.email, username=by_username.username))

    await _assert_untouched(db_session, by_email, email_before)
    await _assert_untouched(db_session, by_username, username_before)
    assert isinstance(outcome, PendingLinkRequiredError), f"got {outcome!r}"
    assert outcome.username == by_email.username


# 7c. Each step checks in its own order. An account with no password that's linked
# elsewhere fails both checks, so the refusal says which one ran first.
@pytest.mark.parametrize(
    ("match", "message"),
    [("email", EMAIL_LINKED_ELSEWHERE), ("username", USERNAME_NO_PASSWORD)],
    ids=["email-checks-the-link-first", "username-checks-the-password-first"],
)
async def test_no_password_and_linked_elsewhere_is_refused_by_the_first_check(
    db_session: AsyncSession, made_users: list[int], match: str, message: str
):
    """Guard: the email step looks at the link first, the username step at the password."""
    old_sub = f"old-{uuid.uuid4().hex[:10]}"
    account = await _account(db_session, made_users, password=False, subject=old_sub)
    before = _snapshot(account)

    outcome = await _login(db_session, _claims_matching(account, match))

    await _assert_untouched(db_session, account, before)
    _assert_refused(outcome, message, account.username)


# 8. No match at all: auto-create, as before.
async def test_no_match_auto_creates_the_user(db_session: AsyncSession, made_users: list[int]):
    claims = _claims()

    outcome = await _login(db_session, claims)

    assert isinstance(outcome, User), f"got {outcome!r}"
    made_users.append(outcome.id)
    assert outcome.username == claims["preferred_username"]
    assert outcome.email == claims["email"]
    assert outcome.oidc_subject == claims["sub"]
    assert outcome.auth_method == "oidc"
    assert outcome.hashed_password is None
    assert outcome.is_active is True
    assert outcome.full_name == "Claimed Name"


# 8b. No match with auto-create off: refused like the others, so it's audited too,
# with the identity it claimed since no account names it.
@pytest.mark.parametrize("blank_username", [False, True], ids=["username", "blank-username"])
async def test_no_match_with_auto_create_off_is_refused_as_no_account(
    db_session: AsyncSession, blank_username: bool
):
    claims = _claims()
    if blank_username:
        claims["preferred_username"] = ""

    try:
        outcome: object = await create_or_update_user_from_oidc(
            db_session, claims, None, {"auto_create_users": "false"}
        )
    except OIDCLoginRefusedError as exc:
        outcome = exc

    claimed = {
        "claimed_email": claims["email"],
        "claimed_username": None if blank_username else claims["preferred_username"],
    }
    _assert_refused(outcome, NO_ACCOUNT, None, claimed)
    created = await db_session.execute(select(User).where(User.oidc_subject == claims["sub"]))
    assert created.scalar_one_or_none() is None


# 8c. The link step refuses a disabled target with the same code as the callback.
async def test_a_disabled_link_target_is_refused_as_account_disabled(
    db_session: AsyncSession, made_users: list[int]
):
    account = await _account(db_session, made_users, active=False)
    token = await create_pending_link_token(
        db_session, account.username, _claims(email=account.email), None, {}
    )

    try:
        outcome: object = await validate_and_consume_pending_link(
            db_session, token, "testpassword123"
        )
    except OIDCLoginRefusedError as exc:
        outcome = exc

    _assert_refused(outcome, DISABLED, account.username)


# 9. An admin-armed relink: the one way an email or username match links.
def _minutes_from_now(minutes: int) -> dt.datetime:
    return utc_now() + dt.timedelta(minutes=minutes)


def _claims_matching(account: User, match: str) -> dict[str, Any]:
    """Claims that reach the account by email only, or by username only."""
    if match == "email":
        return _claims(email=account.email)
    return _claims(username=account.username)


async def _stored(sessionmaker: async_sessionmaker[AsyncSession], user_id: int) -> dict[str, Any]:
    """The committed row, read over a second session so nothing in the test's identity map answers."""
    async with sessionmaker() as fresh:
        user = await fresh.get(User, user_id)
        assert user is not None
        return {field: getattr(user, field) for field in (*_WATCHED, "oidc_relink_until")}


_LINKED_ELSEWHERE = {"email": EMAIL_LINKED_ELSEWHERE, "username": USERNAME_LINKED_ELSEWHERE}


async def _relink_used_rows(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: int
) -> list[AuditLog]:
    """Committed `oidc_relink_used` rows for this account, read over a second session."""
    async with sessionmaker() as fresh:
        rows = await fresh.execute(
            select(AuditLog).where(AuditLog.action == _RELINK_USED, AuditLog.user_id == user_id)
        )
        return list(rows.scalars())


@pytest.mark.parametrize("match", ["email", "username"])
@pytest.mark.parametrize("password", [True, False], ids=["with-password", "sso-only"])
async def test_armed_relink_links_the_new_subject_and_disarms(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    made_users: list[int],
    match: str,
    password: bool,
):
    """The IdP account was re-created, so the same person comes back with a new sub."""
    old_sub = f"old-{uuid.uuid4().hex[:10]}"
    account = await _account(
        db_session,
        made_users,
        password=password,
        subject=old_sub,
        relink_until=_minutes_from_now(30),
    )
    claims = _claims_matching(account, match)
    started = utc_now()

    outcome = await _login(db_session, claims)

    assert isinstance(outcome, User), f"got {outcome!r}"
    assert outcome.id == account.id
    stored = await _stored(test_sessionmaker, account.id)
    assert stored["oidc_subject"] == claims["sub"]
    assert stored["oidc_relink_until"] is None, "the arm must be spent by the link"
    assert stored["oidc_provider"] == "OIDC Provider"
    assert stored["auth_method"] == "oidc"
    assert stored["full_name"] == "Claimed Name"
    assert stored["last_login"] is not None and stored["last_login"] >= started


@pytest.mark.parametrize("match", ["email", "username"])
async def test_expired_relink_counts_as_unarmed(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    made_users: list[int],
    match: str,
):
    old_sub = f"old-{uuid.uuid4().hex[:10]}"
    expired = _minutes_from_now(-1)
    account = await _account(db_session, made_users, subject=old_sub, relink_until=expired)
    before = _snapshot(account)

    outcome = await _login(db_session, _claims_matching(account, match))

    await _assert_untouched(db_session, account, before)
    _assert_refused(outcome, _LINKED_ELSEWHERE[match], account.username)
    stored = await _stored(test_sessionmaker, account.id)
    assert stored["oidc_subject"] == old_sub
    assert stored["oidc_relink_until"] == expired


@pytest.mark.parametrize("match", ["email", "username"])
async def test_armed_relink_on_inactive_account_is_refused_and_stays_armed(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    made_users: list[int],
    match: str,
):
    old_sub = f"old-{uuid.uuid4().hex[:10]}"
    until = _minutes_from_now(30)
    account = await _account(
        db_session, made_users, subject=old_sub, active=False, relink_until=until
    )
    before = _snapshot(account)

    outcome = await _login(db_session, _claims_matching(account, match))

    await _assert_untouched(db_session, account, before)
    _assert_refused(outcome, DISABLED, account.username)
    stored = await _stored(test_sessionmaker, account.id)
    assert stored["oidc_subject"] == old_sub
    assert stored["oidc_relink_until"] == until, "a refused login must not spend the arm"


async def test_relink_spent_since_it_was_read_does_not_link_again(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    made_users: list[int],
):
    """Two SSO logins race for one arm. The loser still holds an armed copy in memory."""
    old_sub = f"old-{uuid.uuid4().hex[:10]}"
    winner_sub = f"winner-{uuid.uuid4().hex[:10]}"
    account = await _account(
        db_session, made_users, subject=old_sub, relink_until=_minutes_from_now(30)
    )
    async with test_sessionmaker() as winner:
        await winner.execute(
            update(User)
            .where(User.id == account.id)
            .values(oidc_subject=winner_sub, oidc_relink_until=None)
        )
        await winner.commit()
    assert account.oidc_relink_until is not None

    outcome = await _login(db_session, _claims(email=account.email))

    _assert_refused(outcome, EMAIL_LINKED_ELSEWHERE, account.username)
    assert (await _stored(test_sessionmaker, account.id))["oidc_subject"] == winner_sub
    # The next commit on this session (the pending-link path makes one) must not
    # carry an audit row the loser staged.
    await db_session.commit()
    assert await _relink_used_rows(test_sessionmaker, account.id) == [], (
        "the loser linked nothing, so it has nothing to audit"
    )


# 10. Using a relink is audited, with where the sign-in came from.
@pytest.mark.parametrize("match", ["email", "username"])
@pytest.mark.parametrize("linked", [True, False], ids=["was-linked", "never-linked"])
async def test_a_used_relink_is_audited_with_its_origin(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    made_users: list[int],
    match: str,
    linked: bool,
):
    old_sub = f"old-{uuid.uuid4().hex[:10]}" if linked else None
    account = await _account(
        db_session, made_users, subject=old_sub, relink_until=_minutes_from_now(30)
    )
    claims = _claims_matching(account, match)
    user_agent = f"relink-test/{uuid.uuid4().hex}"

    outcome = await create_or_update_user_from_oidc(
        db_session, claims, None, {}, ip_address="203.0.113.7", user_agent=user_agent
    )

    assert isinstance(outcome, User) and outcome.id == account.id
    rows = await _relink_used_rows(test_sessionmaker, account.id)
    assert len(rows) == 1, f"expected one {_RELINK_USED} row, got {len(rows)}"
    row = rows[0]
    assert row.username == account.username
    assert row.details == {"old_subject": old_sub, "new_subject": claims["sub"]}
    assert row.ip_address == "203.0.113.7"
    assert row.user_agent == user_agent
    assert row.success == 1


# 11. A working sign-in disarms an open relink, so nobody else can spend it later.
async def test_a_subject_login_disarms_an_open_relink(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    made_users: list[int],
):
    sub = f"sub-{uuid.uuid4().hex[:10]}"
    account = await _account(
        db_session, made_users, subject=sub, relink_until=_minutes_from_now(30)
    )

    outcome = await _login(db_session, _claims(sub=sub))

    assert outcome is account
    stored = await _stored(test_sessionmaker, account.id)
    assert stored["oidc_subject"] == sub
    assert stored["oidc_relink_until"] is None, "the subject login left the relink open"


async def test_a_refused_subject_login_leaves_the_relink_armed(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    made_users: list[int],
):
    """Disabled wins, and a refusal writes nothing, the arm included."""
    sub = f"sub-{uuid.uuid4().hex[:10]}"
    until = _minutes_from_now(30)
    account = await _account(db_session, made_users, subject=sub, active=False, relink_until=until)

    outcome = await _login(db_session, _claims(sub=sub))

    _assert_refused(outcome, DISABLED, account.username)
    assert account.oidc_relink_until == until, "the refusal touched the arm in memory"
    await db_session.flush()
    await db_session.refresh(account)
    assert account.oidc_relink_until == until
    assert (await _stored(test_sessionmaker, account.id))["oidc_relink_until"] == until


async def test_a_password_link_disarms_an_open_relink(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    made_users: list[int],
):
    """The user got to the password page, and an admin armed a relink while they typed."""
    account = await _account(db_session, made_users, relink_until=_minutes_from_now(30))
    claims = _claims(email=account.email)
    token = await create_pending_link_token(db_session, account.username, claims, None, {})

    user, error = await validate_and_consume_pending_link(db_session, token, "testpassword123")

    assert error is None
    assert user is not None and user.id == account.id
    stored = await _stored(test_sessionmaker, account.id)
    assert stored["oidc_subject"] == claims["sub"]
    assert stored["oidc_relink_until"] is None, "the password link left the relink open"


async def test_an_unknown_link_token_is_not_logged(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
):
    """No part of a pending-link token reaches the log: an expired one was real (B2-5)."""
    token = "Zq7" + "x" * 61

    with caplog.at_level("WARNING", logger="app.services.oidc.linking"):
        user, error = await validate_and_consume_pending_link(db_session, token, "whatever")

    assert user is None and error is not None
    assert "not found or expired" in caplog.text
    assert "Zq7xxxx" not in caplog.text

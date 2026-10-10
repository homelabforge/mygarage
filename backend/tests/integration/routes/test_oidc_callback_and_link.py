"""The SSO callback and the Link Account step, driven over HTTP.

The service refuses an SSO login it can't confirm (`OIDCLoginRefusedError`).
The callback used to answer that with a 403 of raw JSON, and every other
failure (a cancelled sign-in, a stale state, a provider that's down or answers
garbage) with a 400, 422 or 500 of the same. Now each one sends the browser to
`/login?sso_error=<code>` with no auth cookie, and a refusal still commits its
audit row. The code is all that goes in the URL; the IdP's own error text only
reaches the log.

The link step used to link a disabled account and only then 403. It now refuses
a disabled account before it looks at the password, and burns the pending link
like every other refusal there.

A relink an admin armed is audited when it's used, with the callback request's
IP and user agent.

A password link is audited in the link's own commit, so a link can't land
without its row, and the row's details are a dict like every other writer's. A
user agent longer than the audit column is cut to fit, since PostgreSQL refuses
the insert otherwise.

The IdP round trip (state, discovery, token exchange, ID token check) is mocked
at the service boundary the route calls; everything after that is real. The
provider failures that used to raise run the real services over a mock HTTP
transport instead.
"""

import datetime as dt
import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable, Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse, urlsplit

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import delete, event, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.constants.oidc import SSOError
from app.exceptions import OIDCLoginRefusedError
from app.main import app
from app.models.audit_log import AuditLog
from app.models.csrf_token import CSRFToken
from app.models.oidc_pending_link import OIDCPendingLink
from app.models.oidc_state import OIDCState
from app.models.settings import Setting
from app.models.user import User
from app.routes.oidc import limiter as oidc_route_limiter
from app.services.oidc import create_pending_link_token, store_oidc_state
from app.services.oidc import linking as oidc_linking
from app.utils.datetime_utils import utc_now
from tests.integration._oidc_refusals import (
    DISABLED,
    NO_ACCOUNT,
    REFUSAL_CODES,
    assert_sent_to_login,
    sets_auth_cookie,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# argon2id of "testpassword123", as in tests/conftest.py.
_HASH = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
_PASSWORD = "testpassword123"
_LAST_LOGIN = dt.datetime(2024, 1, 2, 3, 4, 5)
_WATCHED = ("oidc_subject", "oidc_provider", "auth_method", "last_login", "full_name")

_STATE = {
    "redirect_uri": "http://test/api/auth/oidc/callback",
    "code_verifier": "verifier",
    "nonce": "nonce",
}
_METADATA = {
    "issuer": "https://idp.example",
    "authorization_endpoint": "https://idp.example/authorize",
    "token_endpoint": "https://idp.example/token",
    "jwks_uri": "https://idp.example/jwks",
}
_TOKENS = {"id_token": "id-token"}
_DISCOVERY_URL = "https://idp.example/.well-known/openid-configuration"


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


@pytest.fixture(autouse=True)
def _fresh_link_limit() -> Iterator[None]:
    """The SSO start, the callback and /link-account each allow 5 a minute per address.

    Nearly every request here comes from one address, 127.0.0.1.
    """
    oidc_route_limiter.reset()
    yield
    oidc_route_limiter.reset()


@dataclass(frozen=True)
class _Account:
    """Plain values of a created user. A 403 rolls the shared session back and expires the ORM object."""

    id: int
    username: str
    email: str
    row: dict[str, Any]


@pytest_asyncio.fixture
async def made_users(db_session: AsyncSession) -> AsyncIterator[list[_Account]]:
    """Collects users a test creates and deletes them, and what hangs off them, afterwards."""
    accounts: list[_Account] = []
    yield accounts
    await db_session.rollback()
    ids = [a.id for a in accounts]
    names = [a.username for a in accounts]
    # Core deletes: a linked user owns CSRF tokens, and an ORM delete would null their FK.
    await db_session.execute(delete(OIDCPendingLink).where(OIDCPendingLink.username.in_(names)))
    await db_session.execute(delete(CSRFToken).where(CSRFToken.user_id.in_(ids)))
    await db_session.execute(delete(User).where(User.id.in_(ids)))
    await db_session.commit()


@pytest_asyncio.fixture
async def user_agent(db_session: AsyncSession) -> AsyncIterator[str]:
    """A user agent no other test sends, so this test's audit rows are its own."""
    ua = f"o2-test/{uuid.uuid4().hex}"
    yield ua
    await db_session.rollback()
    await db_session.execute(delete(AuditLog).where(AuditLog.user_agent == ua))
    await db_session.commit()


@pytest_asyncio.fixture
async def long_user_agent(db_session: AsyncSession) -> AsyncIterator[str]:
    """A unique 2,000-character user agent, four times what the audit column holds."""
    prefix = f"o2-test/{uuid.uuid4().hex} "
    ua = prefix + "x" * (2000 - len(prefix))
    yield ua
    await db_session.rollback()
    await db_session.execute(
        delete(AuditLog).where(AuditLog.user_agent.startswith(prefix, autoescape=True))
    )
    await db_session.commit()


async def _account(
    db_session: AsyncSession,
    made_users: list[_Account],
    *,
    active: bool = True,
    relink_until: dt.datetime | None = None,
) -> _Account:
    """A local password account with a fixed past last_login, so any write to it shows."""
    tag = uuid.uuid4().hex[:10]
    user = User(
        username=f"acct_{tag}",
        email=f"acct_{tag}@example.com",
        hashed_password=_HASH,
        full_name="Original Name",
        is_active=active,
        is_admin=False,
        auth_method="local",
        last_login=_LAST_LOGIN,
        oidc_relink_until=relink_until,
    )
    db_session.add(user)
    await db_session.commit()
    account = _Account(user.id, user.username, user.email, _snapshot(user))
    made_users.append(account)
    return account


def _claims(**given: Any) -> dict[str, Any]:
    """ID token claims; anything not given is unique, so it matches nothing."""
    tag = uuid.uuid4().hex[:10]
    return {
        "sub": f"sub-{tag}",
        "email": f"sso_{tag}@example.com",
        "preferred_username": f"sso_{tag}",
        "name": "Claimed Name",
        **given,
    }


@contextmanager
def _idp(
    claims: dict[str, Any] | None,
    *,
    metadata: dict[str, Any] | None = _METADATA,
    tokens: dict[str, Any] | None = _TOKENS,
) -> Generator[None]:
    """A valid state, then discovery, a token exchange and these claims.

    The defaults all succeed, and the token exchange carries no access token.
    Pass None for a step to have it fail the way its service reports it.
    """
    with (
        patch(
            "app.services.oidc.validate_and_consume_state",
            new_callable=AsyncMock,
            return_value=dict(_STATE),
        ),
        patch(
            "app.services.oidc.get_provider_metadata",
            new_callable=AsyncMock,
            return_value=None if metadata is None else dict(metadata),
        ),
        patch(
            "app.services.oidc.exchange_code_for_tokens",
            new_callable=AsyncMock,
            return_value=None if tokens is None else dict(tokens),
        ),
        patch("app.services.oidc.verify_id_token", new_callable=AsyncMock, return_value=claims),
    ):
        yield


@contextmanager
def _idp_over_http(answers: dict[str, tuple[int, bytes]]) -> Generator[None]:
    """A valid state, then the real provider services over a mock transport.

    Each URL gets its canned status and body, anything else a 404. URL
    validation is skipped, since the example hosts don't resolve. Discovery
    fetches what the validator returns, so its stand-in still parses.
    """

    def answer(request: httpx.Request) -> httpx.Response:
        status, body = answers.get(str(request.url), (404, b""))
        return httpx.Response(status, content=body)

    transport = httpx.MockTransport(answer)
    with (
        patch(
            "app.services.oidc.validate_and_consume_state",
            new_callable=AsyncMock,
            return_value=dict(_STATE),
        ),
        patch("app.services.oidc.config.validate_oidc_url", side_effect=urlparse),
        patch("app.services.oidc.tokens.validate_oidc_url"),
        # One httpx module serves both service modules, so this covers all of them.
        patch(
            "app.services.oidc.config.httpx.AsyncClient",
            lambda *_a, **_kw: AsyncClient(transport=transport),
        ),
    ):
        yield


def _json(doc: object) -> bytes:
    return json.dumps(doc).encode()


async def _set_oidc(db_session: AsyncSession, **values: str) -> None:
    """Store oidc_* settings; the autouse fixture puts the originals back."""
    for key, value in values.items():
        db_session.add(Setting(key=f"oidc_{key}", value=value))
    await db_session.commit()


async def _stored_state(
    sessionmaker: async_sessionmaker[AsyncSession], state: str
) -> OIDCState | None:
    async with sessionmaker() as fresh:
        return await fresh.get(OIDCState, state)


async def _new_state(db_session: AsyncSession) -> str:
    """A live state row, as the login start leaves it."""
    state = f"state-{uuid.uuid4().hex}"
    await store_oidc_state(db_session, state, _STATE["redirect_uri"], "nonce", "verifier")
    return state


async def _callback(client: AsyncClient, user_agent: str) -> Response:
    return await client.get(
        "/api/auth/oidc/callback",
        params={"code": "code", "state": "state"},
        headers={"user-agent": user_agent},
        follow_redirects=False,
    )


async def _link(client: AsyncClient, token: str, password: str, user_agent: str) -> Response:
    return await client.post(
        "/api/auth/oidc/link-account",
        json={"token": token, "password": password},
        headers={"user-agent": user_agent},
    )


def _snapshot(user: User) -> dict[str, Any]:
    return {field: getattr(user, field) for field in _WATCHED}


async def _stored_user(sessionmaker: async_sessionmaker[AsyncSession], user_id: int) -> User:
    """The committed row, read over a second session so nothing in the test's identity map leaks in."""
    async with sessionmaker() as fresh:
        user = await fresh.get(User, user_id)
        assert user is not None
        return user


async def _stored_pending_link(
    sessionmaker: async_sessionmaker[AsyncSession], token: str
) -> OIDCPendingLink | None:
    async with sessionmaker() as fresh:
        return await fresh.get(OIDCPendingLink, token)


async def _audit_rows(
    sessionmaker: async_sessionmaker[AsyncSession], user_agent: str
) -> list[AuditLog]:
    """Every committed audit row this test's requests wrote, oldest first."""
    async with sessionmaker() as fresh:
        rows = await fresh.execute(
            select(AuditLog).where(AuditLog.user_agent == user_agent).order_by(AuditLog.id)
        )
        return list(rows.scalars())


async def _refusal_rows(
    sessionmaker: async_sessionmaker[AsyncSession], user_agent: str
) -> list[AuditLog]:
    """Committed `oidc_login_refused` rows this test's requests wrote."""
    async with sessionmaker() as fresh:
        rows = await fresh.execute(
            select(AuditLog).where(
                AuditLog.user_agent == user_agent, AuditLog.action == "oidc_login_refused"
            )
        )
        return list(rows.scalars())


class _AuditInsertError(Exception):
    """Raised in place of an audit row's INSERT."""


@contextmanager
def _failing_audit_insert(action: str) -> Generator[None]:
    """Fail the flush that would insert an audit row with this action."""

    def refuse(_mapper: Any, _connection: Any, target: AuditLog) -> None:
        if target.action == action:
            raise _AuditInsertError(action)

    event.listen(AuditLog, "before_insert", refuse)
    try:
        yield
    finally:
        event.remove(AuditLog, "before_insert", refuse)


def _assert_refusal_row(
    rows: list[AuditLog],
    *,
    reason: str,
    username: str | None,
    extra: dict[str, Any] | None = None,
) -> None:
    """One refusal row; its details are the reason plus ``extra``, and nothing else."""
    assert len(rows) == 1, f"expected one oidc_login_refused row, got {len(rows)}"
    row = rows[0]
    assert row.username == username
    assert row.details == {"reason": reason, **(extra or {})}
    assert row.success == 0
    assert row.ip_address == "127.0.0.1"


class TestCallbackRefusal:
    @pytest.mark.parametrize("code", REFUSAL_CODES)
    @pytest.mark.parametrize("matched", [False, True], ids=["no-match", "matched-account"])
    async def test_a_refused_login_goes_to_the_login_page_with_its_code(
        self,
        client: AsyncClient,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        user_agent: str,
        matched: bool,
        code: str,
    ):
        username = f"refused_{uuid.uuid4().hex[:10]}" if matched else None
        refusal = OIDCLoginRefusedError("x", code=SSOError(code), username=username)

        with (
            _idp(_claims()),
            patch(
                "app.services.oidc.create_or_update_user_from_oidc",
                new_callable=AsyncMock,
                side_effect=refusal,
            ),
        ):
            response = await _callback(client, user_agent)

        assert_sent_to_login(response, code)
        # The audit commit rolls back first, so the row is only here if the route committed it.
        _assert_refusal_row(
            await _refusal_rows(test_sessionmaker, user_agent), reason="x", username=username
        )

    async def test_a_refusals_details_join_the_row_but_never_replace_its_reason(
        self,
        client: AsyncClient,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        user_agent: str,
    ):
        refusal = OIDCLoginRefusedError(
            "x",
            code=SSOError.NO_ACCOUNT,
            details={"reason": "not the message", "claimed_email": "who@example.com"},
        )

        with (
            _idp(_claims()),
            patch(
                "app.services.oidc.create_or_update_user_from_oidc",
                new_callable=AsyncMock,
                side_effect=refusal,
            ),
        ):
            response = await _callback(client, user_agent)

        assert_sent_to_login(response, "no_account")
        _assert_refusal_row(
            await _refusal_rows(test_sessionmaker, user_agent),
            reason="x",
            username=None,
            extra={"claimed_email": "who@example.com"},
        )

    async def test_a_refusal_commits_the_audit_row_and_nothing_else(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        made_users: list[_Account],
        user_agent: str,
    ):
        """The audit commit must not carry a link the refused step had half applied."""
        target = await _account(db_session, made_users)

        async def half_applied_then_refused(db: AsyncSession, *_: Any, **__: Any) -> None:
            user = await db.get(User, target.id)
            assert user is not None
            user.oidc_subject = "sub-half-applied"
            user.auth_method = "oidc"
            raise OIDCLoginRefusedError(
                DISABLED, code=SSOError.ACCOUNT_DISABLED, username=target.username
            )

        with (
            _idp(_claims()),
            patch(
                "app.services.oidc.create_or_update_user_from_oidc",
                new=half_applied_then_refused,
            ),
        ):
            response = await _callback(client, user_agent)

        assert_sent_to_login(response, "account_disabled")
        assert _snapshot(await _stored_user(test_sessionmaker, target.id)) == target.row
        _assert_refusal_row(
            await _refusal_rows(test_sessionmaker, user_agent),
            reason=DISABLED,
            username=target.username,
        )

    async def test_the_callback_backstop_refuses_a_disabled_user_and_audits_it(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        made_users: list[_Account],
        user_agent: str,
    ):
        """The service refuses a disabled account itself, so this is an admin disable mid-login."""
        target = await _account(db_session, made_users, active=False)
        disabled = await db_session.get(User, target.id)

        with (
            _idp(_claims()),
            patch(
                "app.services.oidc.create_or_update_user_from_oidc",
                new_callable=AsyncMock,
                return_value=disabled,
            ),
        ):
            response = await _callback(client, user_agent)

        assert_sent_to_login(response, "account_disabled")
        _assert_refusal_row(
            await _refusal_rows(test_sessionmaker, user_agent),
            reason=DISABLED,
            username=target.username,
        )

    async def test_auto_create_off_is_refused_as_no_account_and_audited(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        user_agent: str,
    ):
        """It used to come back as None and a 500, with no audit row."""
        await _set_oidc(db_session, auto_create_users="false")
        claims = _claims()

        with _idp(claims):
            response = await _callback(client, user_agent)

        assert_sent_to_login(response, "no_account")
        # No account matched, so the claimed identity is how an admin knows who it was.
        _assert_refusal_row(
            await _refusal_rows(test_sessionmaker, user_agent),
            reason=NO_ACCOUNT,
            username=None,
            extra={
                "claimed_email": claims["email"],
                "claimed_username": claims["preferred_username"],
            },
        )
        async with test_sessionmaker() as fresh:
            created = await fresh.execute(select(User).where(User.oidc_subject == claims["sub"]))
            assert created.scalar_one_or_none() is None


class TestCallbackFailure:
    """Every way the callback can't sign anyone in, besides a refusal."""

    async def test_a_cancelled_sign_in_spends_its_state(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
    ):
        """The IdP sends ?error=access_denied and no code. That used to be a 422."""
        state = await _new_state(db_session)

        response = await client.get(
            "/api/auth/oidc/callback",
            params={
                "error": "access_denied",
                "error_description": "The user said no",
                "state": state,
            },
            follow_redirects=False,
        )

        assert_sent_to_login(response, "cancelled")
        assert "said no" not in response.headers["location"]
        assert await _stored_state(test_sessionmaker, state) is None, "the state is still live"

    @pytest.mark.parametrize("error", ["server_error", "login_required", "ACCESS_DENIED"])
    async def test_any_other_idp_error_is_a_failure(self, client: AsyncClient, error: str):
        """Only an exact access_denied is a cancel; any other IdP error is a failure."""
        response = await client.get(
            "/api/auth/oidc/callback", params={"error": error}, follow_redirects=False
        )

        assert_sent_to_login(response, "failed")

    @pytest.mark.parametrize(
        ("send_code", "send_state"),
        [(False, True), (True, False), (False, False)],
        ids=["no-code", "no-state", "neither"],
    )
    async def test_a_missing_code_or_state_is_a_failure(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        send_code: bool,
        send_state: bool,
    ):
        params = {"code": "code"} if send_code else {}
        if send_state:
            params["state"] = await _new_state(db_session)

        response = await client.get(
            "/api/auth/oidc/callback", params=params, follow_redirects=False
        )

        assert_sent_to_login(response, "failed")
        if send_state:
            assert await _stored_state(test_sessionmaker, params["state"]) is None, (
                "the state is still live"
            )

    async def test_the_idp_error_is_logged_once_sanitized_and_kept_out_of_the_url(
        self, client: AsyncClient, caplog: pytest.LogCaptureFixture
    ):
        caplog.set_level(logging.WARNING, logger="app.routes.oidc")

        response = await client.get(
            "/api/auth/oidc/callback",
            params={"error": "invalid_scope\nforged line", "error_description": "Call 555-0100"},
            follow_redirects=False,
        )

        assert_sent_to_login(response, "failed")
        assert "555" not in response.headers["location"]
        warnings = [
            r
            for r in caplog.records
            if r.name == "app.routes.oidc" and r.levelno >= logging.WARNING
        ]
        assert len(warnings) == 1, [r.getMessage() for r in warnings]
        message = warnings[0].getMessage()
        assert "invalid_scope\\nforged line" in message
        assert "Call 555-0100" in message
        assert "\n" not in message

    @pytest.mark.parametrize(
        ("step", "claims"),
        [
            ({"metadata": None}, _claims()),
            ({"tokens": None}, _claims()),
            ({"tokens": {"access_token": "at"}}, _claims()),
            ({}, None),
            # The service gives back None for claims with no email.
            ({}, _claims(email="")),
        ],
        ids=["no-metadata", "no-tokens", "no-id-token", "unverified-id-token", "no-user"],
    )
    async def test_a_provider_step_that_comes_back_empty_is_a_failure(
        self,
        client: AsyncClient,
        user_agent: str,
        step: dict[str, Any],
        claims: dict[str, Any] | None,
    ):
        """These were 500s and a 401 of raw JSON."""
        with _idp(claims, **step):
            response = await _callback(client, user_agent)

        assert_sent_to_login(response, "failed")

    async def test_behind_a_subpath_the_redirect_keeps_the_prefix(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "root_path", "/mygarage")

        response = await client.get(
            "/api/auth/oidc/callback", params={"error": "access_denied"}, follow_redirects=False
        )

        assert response.status_code == 302, response.text
        location = urlsplit(response.headers["location"])
        assert location.path == "/mygarage/login"
        assert parse_qs(location.query) == {"sso_error": ["cancelled"]}


class TestCallbackProviderFailureThatRaises:
    """Provider answers the services used to let escape as a 500."""

    @pytest_asyncio.fixture(autouse=True)
    async def _issuer(self, _oidc_rows: None, db_session: AsyncSession) -> None:
        await _set_oidc(db_session, issuer_url="https://idp.example", client_id="mygarage")

    @pytest.mark.parametrize(
        "discovery",
        [b"<html>not json</html>", _json([]), _json(["issuer"])],
        ids=["malformed-json", "empty-list", "list"],
    )
    async def test_a_discovery_document_that_isnt_an_object_is_a_failure(
        self, client: AsyncClient, user_agent: str, discovery: bytes
    ):
        with _idp_over_http({_DISCOVERY_URL: (200, discovery)}):
            response = await _callback(client, user_agent)

        assert_sent_to_login(response, "failed")

    @pytest.mark.parametrize(
        "jwks", [(503, b"unavailable"), (200, _json({}))], ids=["jwks-503", "jwks-empty-object"]
    )
    async def test_a_jwks_that_cant_be_used_is_a_failure(
        self, client: AsyncClient, user_agent: str, jwks: tuple[int, bytes]
    ):
        answers = {
            _DISCOVERY_URL: (200, _json(_METADATA)),
            _METADATA["token_endpoint"]: (200, _json(_TOKENS)),
            _METADATA["jwks_uri"]: jwks,
        }
        with _idp_over_http(answers):
            response = await _callback(client, user_agent)

        assert_sent_to_login(response, "failed")

    async def test_an_issuer_on_a_blocked_address_is_a_failure(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_agent: str,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """The metadata service raises SSRFProtectionError by contract; the callback catches it."""
        monkeypatch.delenv("MYGARAGE_TRUSTED_HOSTS", raising=False)
        await db_session.execute(
            update(Setting)
            .where(Setting.key == "oidc_issuer_url")
            .values(value="http://127.0.0.1:9000")
        )
        await db_session.commit()

        with patch(
            "app.services.oidc.validate_and_consume_state",
            new_callable=AsyncMock,
            return_value=dict(_STATE),
        ):
            response = await _callback(client, user_agent)

        assert_sent_to_login(response, "failed")


class TestCallbackGuards:
    async def test_a_subject_login_still_signs_in(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        made_users: list[_Account],
        user_agent: str,
    ):
        target = await _account(db_session, made_users)
        sub = f"sub-{uuid.uuid4().hex[:10]}"
        await db_session.execute(
            update(User).where(User.id == target.id).values(oidc_subject=sub, auth_method="oidc")
        )
        await db_session.commit()

        with _idp(_claims(sub=sub)):
            response = await _callback(client, user_agent)

        assert response.status_code == 302, response.text
        location = urlsplit(response.headers["location"])
        assert location.path == "/auth/oidc/success"
        # The CSRF token rides in the fragment, which never goes to a server or its logs.
        assert location.query == ""
        assert set(parse_qs(location.fragment)) == {"csrf_token"}
        assert sets_auth_cookie(response)
        assert await _refusal_rows(test_sessionmaker, user_agent) == []

    async def test_an_unexpected_service_error_still_surfaces(
        self, client: AsyncClient, user_agent: str
    ):
        """Only the refusal and the pending link are caught; a bug isn't a sign-in failure."""
        with (
            _idp(_claims()),
            patch(
                "app.services.oidc.create_or_update_user_from_oidc",
                new_callable=AsyncMock,
                side_effect=RuntimeError("not a refusal"),
            ),
            pytest.raises(RuntimeError, match="not a refusal"),
        ):
            await _callback(client, user_agent)


class TestLinkStepInactiveTarget:
    @pytest.mark.parametrize(
        "password", [_PASSWORD, "not-the-password"], ids=["right-password", "wrong-password"]
    )
    async def test_a_disabled_target_is_refused_before_the_password_and_links_nothing(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        made_users: list[_Account],
        user_agent: str,
        password: str,
    ):
        target = await _account(db_session, made_users, active=False)
        token = await create_pending_link_token(
            db_session, target.username, _claims(email=target.email), None, {}
        )

        response = await _link(client, token, password, user_agent)

        # 403, never 401: a wrong password would only 401 if the password were checked first.
        assert response.status_code == 403, response.text
        assert response.json()["detail"] == DISABLED
        assert not sets_auth_cookie(response)

        stored = await _stored_user(test_sessionmaker, target.id)
        assert stored.oidc_subject is None
        assert stored.auth_method == "local"
        assert _snapshot(stored) == target.row, "the disabled account's row changed"

        # The refusal burns the pending link, like every other refusal in the link step.
        assert await _stored_pending_link(test_sessionmaker, token) is None
        _assert_refusal_row(
            await _refusal_rows(test_sessionmaker, user_agent),
            reason=DISABLED,
            username=target.username,
        )

    async def test_a_user_disabled_mid_link_keeps_the_link_row_and_gets_the_refusal(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        made_users: list[_Account],
        user_agent: str,
    ):
        """An admin disable that lands after the link step's check, before the route's backstop."""
        target = await _account(db_session, made_users)
        token = await create_pending_link_token(
            db_session, target.username, _claims(email=target.email), None, {}
        )
        real_link = oidc_linking.validate_and_consume_pending_link

        async def link_then_disable(
            db: AsyncSession, *args: Any, **kwargs: Any
        ) -> tuple[User | None, str | None]:
            user, error = await real_link(db, *args, **kwargs)
            assert user is not None, error
            async with test_sessionmaker() as admin:
                await admin.execute(update(User).where(User.id == user.id).values(is_active=False))
                await admin.commit()
            await db.refresh(user)
            return user, error

        with patch("app.services.oidc.validate_and_consume_pending_link", new=link_then_disable):
            response = await _link(client, token, _PASSWORD, user_agent)

        assert response.status_code == 403, response.text
        assert response.json()["detail"] == DISABLED
        assert not sets_auth_cookie(response)
        # The link committed with its row, then the backstop refused the login.
        rows = await _audit_rows(test_sessionmaker, user_agent)
        assert [r.action for r in rows] == ["oidc_account_linked", "oidc_login_refused"]
        _assert_refusal_row(rows[1:], reason=DISABLED, username=target.username)


class TestLinkStepRefusalDetails:
    async def test_a_link_step_refusals_details_join_its_audit_row(
        self,
        client: AsyncClient,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        user_agent: str,
    ):
        """The callback already audited a refusal's details; the link step dropped them."""
        refusal = OIDCLoginRefusedError(
            "x",
            code=SSOError.ACCOUNT_DISABLED,
            username="u",
            details={"claimed_email": "who@example.com"},
        )
        with patch(
            "app.services.oidc.validate_and_consume_pending_link",
            new=AsyncMock(side_effect=refusal),
        ):
            response = await _link(client, "any-token", _PASSWORD, user_agent)

        assert response.status_code == 403, response.text
        _assert_refusal_row(
            await _refusal_rows(test_sessionmaker, user_agent),
            reason="x",
            username="u",
            extra={"claimed_email": "who@example.com"},
        )


class TestLinkAudit:
    async def test_a_link_writes_one_row_with_the_username_and_dict_details(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        made_users: list[_Account],
        user_agent: str,
    ):
        target = await _account(db_session, made_users)
        claims = _claims(email=target.email)
        token = await create_pending_link_token(
            db_session, target.username, claims, None, {"provider_name": "Rauthy"}
        )

        response = await _link(client, token, _PASSWORD, user_agent)

        assert response.status_code == 200, response.text
        rows = await _audit_rows(test_sessionmaker, user_agent)
        assert [r.action for r in rows] == ["oidc_account_linked"]
        row = rows[0]
        assert row.user_id == target.id
        assert row.username == target.username
        assert row.details == {"provider": "Rauthy", "oidc_subject": claims["sub"]}
        assert row.success == 1
        assert row.ip_address == "127.0.0.1"

    async def test_a_wrong_password_is_audited_with_the_reason_in_a_dict(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        made_users: list[_Account],
        user_agent: str,
    ):
        target = await _account(db_session, made_users)
        token = await create_pending_link_token(
            db_session, target.username, _claims(email=target.email), None, {}
        )

        response = await _link(client, token, "not-the-password", user_agent)

        assert response.status_code == 401, response.text
        reason = "Invalid password. 2 attempt(s) remaining."
        assert response.json()["detail"] == reason
        rows = await _audit_rows(test_sessionmaker, user_agent)
        assert [(r.action, r.details) for r in rows] == [("oidc_link_failed", {"reason": reason})]

    async def test_a_failed_audit_insert_commits_neither_the_link_nor_the_token(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        made_users: list[_Account],
        user_agent: str,
    ):
        """No link without its audit row, and the token is still there to try again."""
        target = await _account(db_session, made_users)
        token = await create_pending_link_token(
            db_session, target.username, _claims(email=target.email), None, {}
        )

        with _failing_audit_insert("oidc_account_linked"), pytest.raises(_AuditInsertError):
            await _link(client, token, _PASSWORD, user_agent)

        stored = await _stored_user(test_sessionmaker, target.id)
        assert stored.oidc_subject is None, "the link committed without its audit row"
        assert _snapshot(stored) == target.row
        assert await _stored_pending_link(test_sessionmaker, token) is not None
        assert await _audit_rows(test_sessionmaker, user_agent) == []

    async def test_an_overlong_user_agent_is_cut_to_the_column(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        made_users: list[_Account],
        long_user_agent: str,
    ):
        """PostgreSQL refuses a value past String(500), which would fail the link with it."""
        target = await _account(db_session, made_users)
        claims = _claims(email=target.email)
        token = await create_pending_link_token(db_session, target.username, claims, None, {})

        response = await _link(client, token, _PASSWORD, long_user_agent)

        assert response.status_code == 200, response.text
        assert (await _stored_user(test_sessionmaker, target.id)).oidc_subject == claims["sub"]
        async with test_sessionmaker() as fresh:
            rows = list(
                (
                    await fresh.execute(
                        select(AuditLog).where(
                            AuditLog.user_id == target.id,
                            AuditLog.action == "oidc_account_linked",
                        )
                    )
                ).scalars()
            )
        assert len(rows) == 1, f"expected one oidc_account_linked row, got {len(rows)}"
        stored_ua = rows[0].user_agent
        assert stored_ua is not None
        assert len(stored_ua) == 500
        assert stored_ua == long_user_agent[:500]


class TestEmailStepEndToEnd:
    async def test_an_email_match_links_that_account_after_its_password(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        made_users: list[_Account],
        user_agent: str,
    ):
        target = await _account(db_session, made_users)
        # The claimed username matches nothing, so only the email step can find the account.
        claims = _claims(email=target.email)

        with _idp(claims):
            response = await _callback(client, user_agent)

        assert response.status_code == 302, response.text
        assert not sets_auth_cookie(response)
        location = urlsplit(response.headers["location"])
        assert location.path == "/auth/link-account"
        assert location.query == ""
        token = parse_qs(location.fragment)["token"][0]

        pending = await _stored_pending_link(test_sessionmaker, token)
        assert pending is not None
        assert pending.username == target.username
        untouched = await _stored_user(test_sessionmaker, target.id)
        assert untouched.oidc_subject is None, "the callback linked before the password"

        response = await _link(client, token, _PASSWORD, user_agent)

        assert response.status_code == 200, response.text
        assert sets_auth_cookie(response)
        linked = await _stored_user(test_sessionmaker, target.id)
        assert linked.oidc_subject == claims["sub"]
        assert linked.auth_method == "oidc"
        assert await _stored_pending_link(test_sessionmaker, token) is None
        assert await _refusal_rows(test_sessionmaker, user_agent) == []

    async def test_the_pending_link_token_stays_out_of_the_log(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        made_users: list[_Account],
        user_agent: str,
        caplog: pytest.LogCaptureFixture,
    ):
        """The redirect line used to log the whole link URL, live token and all."""
        caplog.set_level(logging.INFO)
        target = await _account(db_session, made_users)

        with _idp(_claims(email=target.email)):
            response = await _callback(client, user_agent)

        assert response.status_code == 302, response.text
        # Read from the row, not the Location, so this holds whatever the URL looks like.
        async with test_sessionmaker() as fresh:
            token = (
                await fresh.execute(
                    select(OIDCPendingLink.token).where(OIDCPendingLink.username == target.username)
                )
            ).scalar_one()
        logged = [r.getMessage() for r in caplog.records if r.levelno >= logging.INFO]
        # The username lines prove the capture saw this callback at all.
        assert any(target.username in m for m in logged), logged
        assert [m for m in logged if token in m] == []


class TestArmedRelinkThroughTheCallback:
    async def test_a_used_relink_is_audited_with_the_requests_ip_and_user_agent(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_sessionmaker: async_sessionmaker[AsyncSession],
        made_users: list[_Account],
        user_agent: str,
    ):
        """The service has no request, so the callback hands it where the sign-in came from."""
        target = await _account(
            db_session, made_users, relink_until=utc_now() + dt.timedelta(minutes=30)
        )
        claims = _claims(email=target.email)

        with _idp(claims):
            response = await _callback(client, user_agent)

        assert response.status_code == 302, response.text
        assert urlsplit(response.headers["location"]).path == "/auth/oidc/success"
        assert sets_auth_cookie(response)
        linked = await _stored_user(test_sessionmaker, target.id)
        assert linked.oidc_subject == claims["sub"]
        assert linked.oidc_relink_until is None

        async with test_sessionmaker() as fresh:
            rows = list(
                (
                    await fresh.execute(
                        select(AuditLog).where(
                            AuditLog.user_agent == user_agent,
                            AuditLog.action == "oidc_relink_used",
                        )
                    )
                ).scalars()
            )
        assert len(rows) == 1, f"expected one oidc_relink_used row, got {len(rows)}"
        assert rows[0].user_id == target.id
        assert rows[0].username == target.username
        assert rows[0].ip_address == "127.0.0.1"
        assert rows[0].details == {"old_subject": None, "new_subject": claims["sub"]}


_AUTH_LIMIT = int(settings.rate_limit_auth.split("/")[0])


class TestSSORateLimit:
    """The SSO start and the callback are limited per client like password login.

    Both are full-page navigations, so a limited attempt lands on the login page
    like every other SSO failure. Other limited routes keep slowapi's JSON 429.
    """

    @pytest.mark.parametrize(
        ("path", "params", "code"),
        [
            ("/api/auth/oidc/login", {}, "failed"),
            ("/api/auth/oidc/callback", {"error": "access_denied"}, "cancelled"),
        ],
        ids=["login", "callback"],
    )
    async def test_each_client_behind_a_trusted_proxy_has_its_own_sso_budget(
        self,
        trust_proxies: Callable[..., None],
        client_via: Callable[[str], AsyncClient],
        path: str,
        params: dict[str, str],
        code: str,
    ) -> None:
        """The start fails with no oidc_* settings; the callback has no state to spend."""
        trust_proxies("10.0.0.0/8")
        proxy = client_via("10.0.0.2")

        async def visit(client_ip: str) -> Response:
            return await proxy.get(
                path,
                params=params,
                headers={"X-Forwarded-For": client_ip},
                follow_redirects=False,
            )

        for _ in range(_AUTH_LIMIT):
            assert_sent_to_login(await visit("198.51.100.7"), code)
        assert_sent_to_login(await visit("198.51.100.7"), "rate_limited")

        # Same proxy, different client: a budget of its own.
        assert_sent_to_login(await visit("198.51.100.8"), code)

    async def test_a_limited_sso_attempt_behind_a_subpath_keeps_the_prefix(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Asks for ``client`` for its get_db override. The path carries the prefix here."""
        monkeypatch.setattr(settings, "root_path", "/mygarage")

        async with AsyncClient(
            transport=ASGITransport(app=app, root_path="/mygarage"), base_url="http://test"
        ) as subpath:
            for _ in range(_AUTH_LIMIT):
                await subpath.get(
                    "/mygarage/api/auth/oidc/callback",
                    params={"error": "access_denied"},
                    follow_redirects=False,
                )
            response = await subpath.get(
                "/mygarage/api/auth/oidc/callback",
                params={"error": "access_denied"},
                follow_redirects=False,
            )

        assert response.status_code == 302, response.text
        location = urlsplit(response.headers["location"])
        assert location.path == "/mygarage/login"
        assert parse_qs(location.query) == {"sso_error": ["rate_limited"]}
        assert not sets_auth_cookie(response)

    async def test_other_limited_routes_still_answer_429_json(
        self, client: AsyncClient, user_agent: str
    ) -> None:
        """/link-account shares the limiter, but it's an XHR, so it keeps slowapi's JSON."""
        for _ in range(_AUTH_LIMIT):
            await _link(client, uuid.uuid4().hex, _PASSWORD, user_agent)
        response = await _link(client, uuid.uuid4().hex, _PASSWORD, user_agent)

        assert response.status_code == 429, response.text
        assert response.json()["error"].startswith("Rate limit exceeded")

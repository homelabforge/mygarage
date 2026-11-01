"""Behind a trusted proxy, rate limits, audit rows and the cookie's scheme follow the real client.

Every limiter keys on ``request.client.host``, the audit rows read it directly,
and ``request_scheme`` reads X-Forwarded-Proto. TrustedProxyMiddleware sits
outermost in ``app.main``, so all of them see the client a trusted proxy names
and never an untrusted peer's forwarding headers.

``client_via(peer)`` sets the TCP peer; the plain ``client`` arrives from
127.0.0.1, which these tests never trust.
"""

import secrets
import uuid
from collections.abc import AsyncIterator, Callable

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.models.audit_log import AuditLog
from app.models.csrf_token import CSRFToken
from app.models.user import User

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

TRUSTED = "10.0.0.0/8"
PROXY = "10.0.0.2"
CLIENT_A = "198.51.100.7"
CLIENT_B = "198.51.100.8"
LIMIT = int(settings.rate_limit_auth.split("/")[0])


@pytest_asyncio.fixture
async def user_agent(db_session: AsyncSession) -> AsyncIterator[str]:
    """A user agent no other test sends, so this test's audit rows are its own."""
    ua = f"trusted-proxy-test/{uuid.uuid4().hex}"
    yield ua
    await db_session.rollback()
    await db_session.execute(delete(AuditLog).where(AuditLog.user_agent == ua))
    await db_session.commit()


@pytest_asyncio.fixture
async def made_users(db_session: AsyncSession) -> AsyncIterator[list[int]]:
    """Collects users a test creates, and deletes them and their relink audit rows afterwards."""
    ids: list[int] = []
    yield ids
    await db_session.rollback()
    await db_session.execute(
        delete(AuditLog).where(
            AuditLog.action == "oidc_relink_allowed",
            AuditLog.resource_id.in_([str(i) for i in ids]),
        )
    )
    await db_session.execute(delete(User).where(User.id.in_(ids)))
    await db_session.commit()


@pytest_asyncio.fixture
async def issued_csrf_tokens(db_session: AsyncSession) -> AsyncIterator[list[str]]:
    """Collects the CSRF tokens a login issues, and deletes them afterwards."""
    tokens: list[str] = []
    yield tokens
    await db_session.rollback()
    await db_session.execute(delete(CSRFToken).where(CSRFToken.token.in_(tokens)))
    await db_session.commit()


async def _failed_login(client: AsyncClient, headers: dict[str, str]) -> Response:
    """A login for a username nobody has, so it's a 401 with no argon2 cost."""
    return await client.post(
        "/api/auth/login",
        json={"username": f"nobody-{uuid.uuid4().hex}", "password": "x"},
        headers=headers,
    )


async def _login(
    client: AsyncClient, test_user: dict[str, object], issued_csrf_tokens: list[str]
) -> Response:
    """Log in as ``test_user`` from behind a TLS-terminating proxy, or something claiming to be one."""
    response = await client.post(
        "/api/auth/login",
        json={"username": test_user["username"], "password": "testpassword123"},
        headers={"X-Forwarded-Proto": "https"},
    )
    if response.status_code == 200:
        issued_csrf_tokens.append(response.json()["csrf_token"])
    return response


async def _sso_only_user(db_session: AsyncSession, made_users: list[int]) -> int:
    """An SSO-only account an admin can arm a relink on."""
    tag = uuid.uuid4().hex[:10]
    user = User(
        username=f"proxy_{tag}",
        email=f"proxy_{tag}@example.com",
        hashed_password=None,
        is_active=True,
        is_admin=False,
        oidc_subject=f"sub-{tag}",
        oidc_provider="Rauthy",
        auth_method="oidc",
    )
    db_session.add(user)
    await db_session.commit()
    made_users.append(user.id)
    return user.id


async def test_two_clients_behind_one_proxy_have_separate_login_budgets(
    trust_proxies: Callable[..., None],
    client_via: Callable[[str], AsyncClient],
) -> None:
    trust_proxies(TRUSTED)
    proxy = client_via(PROXY)

    for _ in range(LIMIT):
        response = await _failed_login(proxy, {"X-Forwarded-For": CLIENT_A})
        assert response.status_code == 401, response.text
    assert (await _failed_login(proxy, {"X-Forwarded-For": CLIENT_A})).status_code == 429

    # Same proxy, different client: a budget of its own.
    response = await _failed_login(proxy, {"X-Forwarded-For": CLIENT_B})
    assert response.status_code == 401, response.text


async def test_untrusted_peer_cannot_pick_its_limiter_key(
    trust_proxies: Callable[..., None],
    client: AsyncClient,
) -> None:
    trust_proxies(TRUSTED)

    for n in range(LIMIT):
        response = await _failed_login(client, {"X-Forwarded-For": f"203.0.113.{n + 1}"})
        assert response.status_code == 401, response.text

    response = await _failed_login(client, {"X-Forwarded-For": "203.0.113.200"})
    assert response.status_code == 429, response.text


@pytest.mark.parametrize(
    ("client_ip_header", "sent", "expected"),
    [
        ("", {"X-Forwarded-For": CLIENT_A}, CLIENT_A),
        (
            "CF-Connecting-IP",
            {"CF-Connecting-IP": "203.0.113.50", "X-Forwarded-For": "10.0.0.9"},
            "203.0.113.50",
        ),
    ],
    ids=["xff", "client_ip_header"],
)
async def test_request_origin_audit_row_records_the_client(
    trust_proxies: Callable[..., None],
    client_via: Callable[[str], AsyncClient],
    test_sessionmaker: async_sessionmaker[AsyncSession],
    user_agent: str,
    client_ip_header: str,
    sent: dict[str, str],
    expected: str,
) -> None:
    trust_proxies(TRUSTED, header=client_ip_header)

    response = await client_via(PROXY).post(
        "/api/auth/oidc/link-account",
        json={"token": secrets.token_hex(32), "password": "x"},
        headers={**sent, "User-Agent": user_agent},
    )

    assert response.status_code == 401, response.text
    assert response.json()["detail"] == "Link expired, please log in again"
    async with test_sessionmaker() as fresh:
        rows = await fresh.execute(select(AuditLog).where(AuditLog.user_agent == user_agent))
        assert [(r.action, r.ip_address) for r in rows.scalars()] == [
            ("oidc_link_failed", expected)
        ]


async def test_log_event_audit_row_records_the_client(
    trust_proxies: Callable[..., None],
    client_via: Callable[[str], AsyncClient],
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    made_users: list[int],
    auth_headers: dict[str, str],
) -> None:
    trust_proxies(TRUSTED)
    target = await _sso_only_user(db_session, made_users)

    response = await client_via(PROXY).post(
        f"/api/auth/users/{target}/oidc-relink",
        headers={**auth_headers, "X-Forwarded-For": CLIENT_A},
    )

    assert response.status_code == 200, response.text
    async with test_sessionmaker() as fresh:
        rows = await fresh.execute(
            select(AuditLog).where(
                AuditLog.action == "oidc_relink_allowed", AuditLog.resource_id == str(target)
            )
        )
        assert [r.ip_address for r in rows.scalars()] == [CLIENT_A]


async def test_forwarded_proto_from_an_untrusted_peer_is_ignored(
    trust_proxies: Callable[..., None],
    client: AsyncClient,
    test_user: dict[str, object],
    issued_csrf_tokens: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trust_proxies(TRUSTED)
    monkeypatch.delenv("JWT_COOKIE_SECURE", raising=False)

    response = await _login(client, test_user, issued_csrf_tokens)

    assert response.status_code == 200, response.text
    cookie = response.headers.get("set-cookie", "").lower()
    assert settings.jwt_cookie_name.lower() in cookie
    assert "; secure" not in cookie


async def test_forwarded_proto_from_a_trusted_peer_is_honoured(
    trust_proxies: Callable[..., None],
    client_via: Callable[[str], AsyncClient],
    test_user: dict[str, object],
    issued_csrf_tokens: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trust_proxies(TRUSTED)
    monkeypatch.delenv("JWT_COOKIE_SECURE", raising=False)

    response = await _login(client_via(PROXY), test_user, issued_csrf_tokens)

    assert response.status_code == 200, response.text
    cookie = response.headers.get("set-cookie", "").lower()
    assert settings.jwt_cookie_name.lower() in cookie
    assert "; secure" in cookie

"""OIDC settings that did nothing, or locked every SSO user out.

- A blank `scopes` was stored as '' and sent as `scope=`.
- A blank `email_claim` looked up the claim '' and found no email, so every
  OIDC login was refused.
- The admin page writes `full_name_claim`, but login read `name_claim` and the
  password-link path hard-coded "name", so the setting had no effect.
- The admin GET papered over all of it by showing the defaults.

A blank setting now means its default, and the full-name claim resolves
`full_name_claim`, then the seeded `name_claim`, then "name".
"""

import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.oidc_state import OIDCState
from app.models.settings import Setting
from app.models.user import User
from app.services.oidc import (
    create_authorization_url,
    create_or_update_user_from_oidc,
    create_pending_link_token,
    validate_and_consume_pending_link,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# argon2id of "testpassword123", as in tests/conftest.py.
_HASH = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
_METADATA = {"authorization_endpoint": "https://idp.example/authorize"}


@pytest_asyncio.fixture(autouse=True)
async def _oidc_rows(db_session: AsyncSession):
    """Start with no oidc_* settings and put the originals back afterwards."""
    rows = (await db_session.execute(select(Setting).where(Setting.key.like("oidc_%")))).scalars()
    # The raw stored form, so an unreadable secret's ciphertext survives (R2-10).
    saved = [(r.key, r.stored_value, r.category, r.description, r.encrypted) for r in rows]
    await db_session.execute(delete(Setting).where(Setting.key.like("oidc_%")))
    await db_session.commit()
    yield
    await db_session.rollback()
    await db_session.execute(delete(Setting).where(Setting.key.like("oidc_%")))
    for key, stored_value, category, description, encrypted in saved:
        db_session.add(
            Setting(
                key=key,
                stored_value=stored_value,
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
        delete(AuditLog).where(AuditLog.action == "oidc_account_linked", AuditLog.user_id.in_(ids))
    )
    for user_id in ids:
        user = await db_session.get(User, user_id)
        if user is not None:
            await db_session.delete(user)
    await db_session.commit()


async def _store(db_session: AsyncSession, values: dict[str, str]) -> None:
    for key, value in values.items():
        db_session.add(Setting(key=f"oidc_{key}", value=value))
    await db_session.commit()


def _claims(**extra: str) -> dict[str, str]:
    tag = uuid.uuid4().hex[:10]
    return {
        "sub": f"sub-{tag}",
        "email": f"sso_{tag}@example.com",
        "preferred_username": f"sso_{tag}",
        **extra,
    }


async def _scope_sent(db_session: AsyncSession, config: dict[str, str]) -> str:
    url, state = await create_authorization_url(db_session, config, _METADATA, "https://mg.example")
    await db_session.execute(delete(OIDCState).where(OIDCState.state == state))
    await db_session.commit()
    return parse_qs(urlsplit(url).query, keep_blank_values=True)["scope"][0]


@pytest.mark.parametrize("blank", ["", "   "])
async def test_blank_scopes_send_the_default(db_session: AsyncSession, blank: str):
    assert (
        await _scope_sent(db_session, {"client_id": "c", "scopes": blank}) == "openid profile email"
    )


async def test_set_scopes_are_sent(db_session: AsyncSession):
    assert (
        await _scope_sent(db_session, {"client_id": "c", "scopes": " openid email "})
        == "openid email"
    )


async def test_blank_email_claim_still_finds_the_email(db_session: AsyncSession, made_users):
    claims = _claims()
    user = await create_or_update_user_from_oidc(
        db_session, claims, None, {"email_claim": "", "username_claim": " "}
    )
    assert user is not None
    made_users.append(user.id)
    assert user.email == claims["email"]
    assert user.username == claims["preferred_username"]


async def test_a_custom_full_name_claim_is_used_on_create(db_session: AsyncSession, made_users):
    user = await create_or_update_user_from_oidc(
        db_session,
        _claims(display_name="Pat Doe", name="Wrong Name"),
        None,
        {"full_name_claim": "display_name", "name_claim": "name"},
    )
    assert user is not None
    made_users.append(user.id)
    assert user.full_name == "Pat Doe"


async def test_the_seeded_name_claim_is_the_fallback(db_session: AsyncSession, made_users):
    user = await create_or_update_user_from_oidc(
        db_session,
        _claims(legacy_name="Legacy Pat", name="Wrong Name"),
        None,
        {"full_name_claim": "", "name_claim": "legacy_name"},
    )
    assert user is not None
    made_users.append(user.id)
    assert user.full_name == "Legacy Pat"


async def test_a_custom_full_name_claim_is_used_on_link(db_session: AsyncSession, made_users):
    tag = uuid.uuid4().hex[:10]
    local = User(
        username=f"link_{tag}",
        email=f"link_{tag}@example.com",
        hashed_password=_HASH,
        is_active=True,
        is_admin=False,
        full_name="Before Link",
    )
    db_session.add(local)
    await db_session.commit()
    made_users.append(local.id)
    await _store(db_session, {"full_name_claim": "display_name"})

    token = await create_pending_link_token(
        db_session,
        local.username,
        {"sub": f"sub-{tag}", "display_name": "Linked Pat", "name": "Wrong Name"},
        None,
        {},
    )
    user, error = await validate_and_consume_pending_link(db_session, token, "testpassword123")

    assert error is None
    assert user is not None
    assert user.full_name == "Linked Pat"


class TestAdminConfig:
    async def test_get_shows_what_login_will_use(
        self, client: AsyncClient, auth_headers, db_session: AsyncSession
    ):
        await _store(
            db_session,
            {"scopes": "  ", "email_claim": "", "username_claim": "", "name_claim": "legacy_name"},
        )
        r = await client.get("/api/auth/oidc/config/admin", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["scopes"] == "openid profile email"
        assert body["email_claim"] == "email"
        assert body["username_claim"] == "preferred_username"
        assert body["full_name_claim"] == "legacy_name"

    async def test_put_stores_the_stripped_values(
        self, client: AsyncClient, auth_headers, db_session: AsyncSession
    ):
        payload = {
            "enabled": False,
            "provider_name": "Rauthy",
            "issuer_url": "https://auth.example.com",
            "client_id": "id",
            "client_secret": "",
            "scopes": "  openid email ",
            "auto_create_users": True,
            "admin_group": "",
            "username_claim": " preferred_username ",
            "email_claim": " mail ",
            "full_name_claim": " display_name ",
        }
        r = await client.put("/api/auth/oidc/config/admin", headers=auth_headers, json=payload)
        assert r.status_code == 200, r.text

        stored = {
            s.key: s.value
            for s in (
                await db_session.execute(select(Setting).where(Setting.key.like("oidc_%")))
            ).scalars()
        }
        assert stored["oidc_scopes"] == "openid email"
        assert stored["oidc_username_claim"] == "preferred_username"
        assert stored["oidc_email_claim"] == "mail"
        assert stored["oidc_full_name_claim"] == "display_name"

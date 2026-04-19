"""Integration tests for /api/auth/me/widget-keys.

Covers the user-facing key management surface:
- Creation returns the plaintext secret exactly once
- List returns only the caller's keys, never hashes or plaintext
- Revoke invalidates the key for widget consumption immediately
- auth_mode=none returns the dedicated 400 (not a generic 401)
- Per-user isolation (DELETE of another user's key → 404, not 403)
- End-to-end: create key → use on /api/widget/* → 200 → revoke → 401

The /api/widget/* suite in test_widget.py proves the consumption side; this
file proves the management + issuance side and the bridge between them.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.models.settings import Setting
from app.models.user import User
from app.models.widget_api_key import WidgetApiKey
from app.services.auth import create_access_token
from app.services.widget_auth import WIDGET_KEY_PREFIX

TEST_PASSWORD_HASH = (
    "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw"
    "$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
)


@pytest_asyncio.fixture
async def set_auth_mode(db_session):
    async def _apply(mode: str | None) -> None:
        existing = (
            await db_session.execute(select(Setting).where(Setting.key == "auth_mode"))
        ).scalar_one_or_none()
        if existing is None:
            if mode is not None:
                db_session.add(Setting(key="auth_mode", value=mode))
        else:
            if mode is None:
                await db_session.delete(existing)
            else:
                existing.value = mode
        await db_session.commit()

    yield _apply
    await _apply("local")


@pytest_asyncio.fixture
async def keys_user(db_session) -> User:
    """Unique-per-run user so key counts don't bleed across tests."""
    u = User(
        username=f"wk_user_{uuid.uuid4().hex[:8]}",
        email=f"wk_user_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=TEST_PASSWORD_HASH,
        is_active=True,
        is_admin=False,
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


def _auth_headers(user: User) -> dict[str, str]:
    """JWT bearer for the given user. Token payload matches get_current_user's
    expectations: `sub` holds the numeric user_id (as a string) and `username`
    is carried separately."""
    token = create_access_token({"sub": str(user.id), "username": user.username})
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
@pytest.mark.asyncio
class TestCreateWidgetKey:
    async def test_201_returns_secret_once(
        self, client: AsyncClient, db_session, keys_user, set_auth_mode
    ):
        await set_auth_mode("local")
        resp = await client.post(
            "/api/auth/me/widget-keys",
            json={"name": "homepage"},
            headers=_auth_headers(keys_user),
        )
        assert resp.status_code == 201
        body = resp.json()
        # Secret comes back once, with the expected prefix.
        assert body["secret"].startswith(WIDGET_KEY_PREFIX)
        assert len(body["secret"]) > 40
        # Display fields are sanitized.
        assert body["key_prefix"].startswith(WIDGET_KEY_PREFIX)
        assert "key_hash" not in body
        # Listing the key later must not leak the plaintext again.
        list_resp = await client.get("/api/auth/me/widget-keys", headers=_auth_headers(keys_user))
        listed = list_resp.json()["keys"][0]
        assert "secret" not in listed
        assert "key_hash" not in listed

    async def test_selected_vins_requires_vin_list(
        self, client: AsyncClient, keys_user, set_auth_mode
    ):
        await set_auth_mode("local")
        resp = await client.post(
            "/api/auth/me/widget-keys",
            json={"name": "bad", "scope": "selected_vins"},
            headers=_auth_headers(keys_user),
        )
        assert resp.status_code == 422

    async def test_empty_name_rejected(self, client: AsyncClient, keys_user, set_auth_mode):
        await set_auth_mode("local")
        resp = await client.post(
            "/api/auth/me/widget-keys",
            json={"name": ""},
            headers=_auth_headers(keys_user),
        )
        assert resp.status_code == 422

    async def test_unauthenticated_401(self, client: AsyncClient, set_auth_mode):
        await set_auth_mode("local")
        resp = await client.post("/api/auth/me/widget-keys", json={"name": "x"})
        assert resp.status_code == 401

    async def test_400_when_auth_mode_none(
        self, client: AsyncClient, db_session, keys_user, set_auth_mode
    ):
        # require_auth_enabled must fire BEFORE get_current_active_user so
        # the 400 body distinguishes "auth is off" from "token invalid".
        await set_auth_mode("none")
        try:
            resp = await client.post(
                "/api/auth/me/widget-keys",
                json={"name": "x"},
                headers=_auth_headers(keys_user),
            )
            assert resp.status_code == 400
            body = resp.json()
            # Detail is the structured contract body.
            assert body["detail"]["detail"] == "widget_keys_require_auth"
        finally:
            await set_auth_mode("local")


@pytest.mark.integration
@pytest.mark.asyncio
class TestListWidgetKeys:
    async def test_lists_only_own_keys(
        self, client: AsyncClient, db_session, keys_user, set_auth_mode
    ):
        await set_auth_mode("local")
        # Create two keys for this user and one for a different user.
        await client.post(
            "/api/auth/me/widget-keys",
            json={"name": "a"},
            headers=_auth_headers(keys_user),
        )
        await client.post(
            "/api/auth/me/widget-keys",
            json={"name": "b"},
            headers=_auth_headers(keys_user),
        )
        other = User(
            username=f"wk_other_{uuid.uuid4().hex[:8]}",
            email=f"wk_other_{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=TEST_PASSWORD_HASH,
            is_active=True,
            is_admin=False,
        )
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        await client.post(
            "/api/auth/me/widget-keys",
            json={"name": "not mine"},
            headers=_auth_headers(other),
        )

        resp = await client.get("/api/auth/me/widget-keys", headers=_auth_headers(keys_user))
        assert resp.status_code == 200
        names = [k["name"] for k in resp.json()["keys"]]
        assert "a" in names
        assert "b" in names
        assert "not mine" not in names

    async def test_400_when_auth_mode_none(self, client: AsyncClient, keys_user, set_auth_mode):
        await set_auth_mode("none")
        try:
            resp = await client.get("/api/auth/me/widget-keys", headers=_auth_headers(keys_user))
            assert resp.status_code == 400
        finally:
            await set_auth_mode("local")


@pytest.mark.integration
@pytest.mark.asyncio
class TestRevokeWidgetKey:
    async def test_revoke_sets_revoked_at(
        self, client: AsyncClient, db_session, keys_user, set_auth_mode
    ):
        await set_auth_mode("local")
        created = (
            await client.post(
                "/api/auth/me/widget-keys",
                json={"name": "to revoke"},
                headers=_auth_headers(keys_user),
            )
        ).json()
        resp = await client.delete(
            f"/api/auth/me/widget-keys/{created['id']}",
            headers=_auth_headers(keys_user),
        )
        assert resp.status_code == 204

        # Row persists with revoked_at set (soft-revoke for audit).
        persisted = (
            await db_session.execute(select(WidgetApiKey).where(WidgetApiKey.id == created["id"]))
        ).scalar_one()
        assert persisted.revoked_at is not None

    async def test_delete_other_users_key_returns_404(
        self, client: AsyncClient, db_session, keys_user, set_auth_mode
    ):
        await set_auth_mode("local")
        other = User(
            username=f"wk_other2_{uuid.uuid4().hex[:8]}",
            email=f"wk_other2_{uuid.uuid4().hex[:8]}@example.com",
            hashed_password=TEST_PASSWORD_HASH,
            is_active=True,
            is_admin=False,
        )
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other)
        created = (
            await client.post(
                "/api/auth/me/widget-keys",
                json={"name": "other's"},
                headers=_auth_headers(other),
            )
        ).json()
        # keys_user tries to delete other's key — should be 404, not 403.
        resp = await client.delete(
            f"/api/auth/me/widget-keys/{created['id']}",
            headers=_auth_headers(keys_user),
        )
        assert resp.status_code == 404

    async def test_delete_nonexistent_key_returns_404(
        self, client: AsyncClient, keys_user, set_auth_mode
    ):
        await set_auth_mode("local")
        resp = await client.delete(
            "/api/auth/me/widget-keys/999999", headers=_auth_headers(keys_user)
        )
        assert resp.status_code == 404

    async def test_revoke_idempotent(self, client: AsyncClient, keys_user, set_auth_mode):
        await set_auth_mode("local")
        created = (
            await client.post(
                "/api/auth/me/widget-keys",
                json={"name": "double revoke"},
                headers=_auth_headers(keys_user),
            )
        ).json()
        first = await client.delete(
            f"/api/auth/me/widget-keys/{created['id']}",
            headers=_auth_headers(keys_user),
        )
        second = await client.delete(
            f"/api/auth/me/widget-keys/{created['id']}",
            headers=_auth_headers(keys_user),
        )
        assert first.status_code == 204
        assert second.status_code == 204


@pytest.mark.integration
@pytest.mark.asyncio
class TestCreateThenUseThenRevoke:
    """Bridge test: the key issued via POST must work on /api/widget/*,
    and a DELETE must flip it to 401 on the same consumption endpoint."""

    async def test_end_to_end_key_lifecycle(self, client: AsyncClient, keys_user, set_auth_mode):
        await set_auth_mode("local")
        created = (
            await client.post(
                "/api/auth/me/widget-keys",
                json={"name": "lifecycle"},
                headers=_auth_headers(keys_user),
            )
        ).json()
        secret = created["secret"]

        ok = await client.get("/api/widget/summary", headers={"X-API-Key": secret})
        assert ok.status_code == 200

        await client.delete(
            f"/api/auth/me/widget-keys/{created['id']}",
            headers=_auth_headers(keys_user),
        )

        after = await client.get("/api/widget/summary", headers={"X-API-Key": secret})
        assert after.status_code == 401

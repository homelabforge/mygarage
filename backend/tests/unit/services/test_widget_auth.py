"""Unit tests for widget API key authentication.

Covers the token helpers (generation, hashing, display prefix) and the two
FastAPI dependencies (`require_widget_key`, `require_auth_enabled`) that gate
the homepage widget surface.
"""

import asyncio
import hashlib

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.models.settings import Setting
from app.models.user import User
from app.models.widget_api_key import WidgetApiKey
from app.services.widget_auth import (
    DISPLAY_PREFIX_LEN,
    LAST_USED_THROTTLE,
    WIDGET_KEY_PREFIX,
    display_prefix,
    generate_widget_key,
    hash_widget_key,
    require_auth_enabled,
    require_widget_key,
)
from app.utils.datetime_utils import utc_now

TEST_PASSWORD_HASH = (
    "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw"
    "$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"
)


class TestTokenHelpers:
    """Pure-function token helpers — no DB fixtures required."""

    def test_generate_prefix(self):
        assert generate_widget_key().startswith(WIDGET_KEY_PREFIX)

    def test_generate_length(self):
        # prefix "mgwk_" (5) + ~43 chars from token_urlsafe(32)
        assert len(generate_widget_key()) > 40

    def test_generate_unique(self):
        keys = {generate_widget_key() for _ in range(200)}
        assert len(keys) == 200

    def test_hash_deterministic(self):
        token = "mgwk_deterministic_example"
        assert hash_widget_key(token) == hash_widget_key(token)

    def test_hash_is_sha256_hex(self):
        token = "mgwk_abc"
        expected = hashlib.sha256(token.encode()).hexdigest()
        assert hash_widget_key(token) == expected
        assert len(hash_widget_key(token)) == 64

    def test_hash_differs_per_token(self):
        assert hash_widget_key("mgwk_a") != hash_widget_key("mgwk_b")

    def test_display_prefix_length(self):
        token = generate_widget_key()
        assert len(display_prefix(token)) == DISPLAY_PREFIX_LEN
        assert display_prefix(token) == token[:DISPLAY_PREFIX_LEN]


@pytest_asyncio.fixture
async def _set_auth_mode(db_session):
    """Return a helper that sets the auth_mode setting for the duration of a test."""

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
    # Reset to 'local' (default) after each test that uses this fixture.
    await _apply("local")


@pytest_asyncio.fixture
async def widget_user(db_session) -> User:
    """Active, non-admin user that widget keys attach to."""
    result = await db_session.execute(select(User).where(User.username == "widget_user"))
    user = result.scalar_one_or_none()
    if not user:
        user = User(
            username="widget_user",
            email="widget_user@example.com",
            hashed_password=TEST_PASSWORD_HASH,
            is_active=True,
            is_admin=False,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
    else:
        user.is_active = True
        await db_session.commit()
    return user


async def _make_key(db_session, user: User, **overrides) -> tuple[str, WidgetApiKey]:
    """Create a widget key for `user` and return (plaintext, persisted row)."""
    plaintext = generate_widget_key()
    key = WidgetApiKey(
        user_id=user.id,
        name=overrides.get("name", "test key"),
        key_hash=hash_widget_key(plaintext),
        key_prefix=display_prefix(plaintext),
        scope=overrides.get("scope", "all_vehicles"),
        allowed_vins=overrides.get("allowed_vins"),
        revoked_at=overrides.get("revoked_at"),
        last_used_at=overrides.get("last_used_at"),
    )
    db_session.add(key)
    await db_session.commit()
    await db_session.refresh(key)
    return plaintext, key


class TestRequireAuthEnabled:
    """Dependency used by key-management routes to 400 on auth_mode=none."""

    @pytest.mark.asyncio
    async def test_passes_when_local(self, db_session, _set_auth_mode):
        await _set_auth_mode("local")
        # Returns None on success; must not raise.
        assert await require_auth_enabled(db_session) is None

    @pytest.mark.asyncio
    async def test_passes_when_oidc(self, db_session, _set_auth_mode):
        await _set_auth_mode("oidc")
        assert await require_auth_enabled(db_session) is None

    @pytest.mark.asyncio
    async def test_raises_400_when_none(self, db_session, _set_auth_mode):
        await _set_auth_mode("none")
        with pytest.raises(HTTPException) as exc:
            await require_auth_enabled(db_session)
        assert exc.value.status_code == 400
        assert exc.value.detail["detail"] == "widget_keys_require_auth"


class TestRequireWidgetKey:
    """Dependency used by /api/widget/* to authenticate polled requests."""

    @pytest.mark.asyncio
    async def test_success_returns_user_and_key(self, db_session, widget_user, _set_auth_mode):
        await _set_auth_mode("local")
        plaintext, key = await _make_key(db_session, widget_user)
        user, resolved_key = await require_widget_key(x_api_key=plaintext, db=db_session)
        assert user.id == widget_user.id
        assert resolved_key.id == key.id

    @pytest.mark.asyncio
    async def test_401_when_auth_mode_none(self, db_session, widget_user, _set_auth_mode):
        await _set_auth_mode("none")
        plaintext, _ = await _make_key(db_session, widget_user)
        with pytest.raises(HTTPException) as exc:
            await require_widget_key(x_api_key=plaintext, db=db_session)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_401_when_header_missing(self, db_session, _set_auth_mode):
        await _set_auth_mode("local")
        with pytest.raises(HTTPException) as exc:
            await require_widget_key(x_api_key=None, db=db_session)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_401_when_prefix_wrong(self, db_session, _set_auth_mode):
        await _set_auth_mode("local")
        with pytest.raises(HTTPException) as exc:
            await require_widget_key(x_api_key="ll_notourprefix", db=db_session)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_401_when_hash_unknown(self, db_session, _set_auth_mode):
        await _set_auth_mode("local")
        with pytest.raises(HTTPException) as exc:
            await require_widget_key(
                x_api_key=f"{WIDGET_KEY_PREFIX}unknown_but_well_formed", db=db_session
            )
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_401_when_revoked(self, db_session, widget_user, _set_auth_mode):
        await _set_auth_mode("local")
        plaintext, _ = await _make_key(db_session, widget_user, revoked_at=utc_now())
        with pytest.raises(HTTPException) as exc:
            await require_widget_key(x_api_key=plaintext, db=db_session)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_401_when_user_inactive(self, db_session, widget_user, _set_auth_mode):
        await _set_auth_mode("local")
        plaintext, _ = await _make_key(db_session, widget_user)
        widget_user.is_active = False
        await db_session.commit()
        try:
            with pytest.raises(HTTPException) as exc:
                await require_widget_key(x_api_key=plaintext, db=db_session)
            assert exc.value.status_code == 401
        finally:
            # Restore for subsequent tests in the same session.
            widget_user.is_active = True
            await db_session.commit()

    @pytest.mark.asyncio
    async def test_last_used_set_on_first_call(self, db_session, widget_user, _set_auth_mode):
        await _set_auth_mode("local")
        plaintext, key = await _make_key(db_session, widget_user)
        assert key.last_used_at is None
        await require_widget_key(x_api_key=plaintext, db=db_session)
        await db_session.refresh(key)
        assert key.last_used_at is not None

    @pytest.mark.asyncio
    async def test_last_used_throttled_within_window(self, db_session, widget_user, _set_auth_mode):
        await _set_auth_mode("local")
        plaintext, key = await _make_key(db_session, widget_user)
        await require_widget_key(x_api_key=plaintext, db=db_session)
        await db_session.refresh(key)
        first_seen = key.last_used_at
        assert first_seen is not None

        # Tiny real-clock gap, well under LAST_USED_THROTTLE — must NOT update.
        await asyncio.sleep(0.05)
        await require_widget_key(x_api_key=plaintext, db=db_session)
        await db_session.refresh(key)
        assert key.last_used_at == first_seen

    @pytest.mark.asyncio
    async def test_last_used_updates_after_throttle_window(
        self, db_session, widget_user, _set_auth_mode
    ):
        await _set_auth_mode("local")
        plaintext, key = await _make_key(db_session, widget_user)
        # Pre-age last_used_at beyond the throttle so the next call refreshes it.
        key.last_used_at = utc_now() - (LAST_USED_THROTTLE * 2)
        await db_session.commit()
        await db_session.refresh(key)
        aged = key.last_used_at
        assert aged is not None

        await require_widget_key(x_api_key=plaintext, db=db_session)
        await db_session.refresh(key)
        assert key.last_used_at is not None
        assert key.last_used_at > aged

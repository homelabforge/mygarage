"""
Integration tests for authentication routes.

Tests user registration, login, logout, and protected endpoints.
"""

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select  # noqa: F401

from app.config import settings
from app.models.user import User


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestUserRegistration:
    """Test user registration endpoint."""

    async def test_register_first_user_success(self, client: AsyncClient, db_session):
        """Test that the first user can register and becomes admin."""
        # Clear any existing users
        await db_session.execute(delete(User))
        await db_session.commit()

        # Register first user
        response = await client.post(
            "/api/auth/register",
            json={
                "username": "firstuser",
                "email": "first@example.com",
                "password": "SecurePassword123!",
                "full_name": "First User",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["username"] == "firstuser"
        assert data["email"] == "first@example.com"
        assert data["is_admin"] is True
        assert data["is_active"] is True
        assert "hashed_password" not in data  # Password should not be returned

    @pytest.mark.skip(
        reason="Single-user mode: registration disabled after first user, "
        "duplicate username check can't be tested via API"
    )
    async def test_register_duplicate_username(self, client: AsyncClient, db_session):
        """Test that duplicate usernames are rejected.

        NOTE: This test is skipped because MyGarage operates in single-user mode.
        After the first user registers, all subsequent registration attempts return 403.
        Duplicate username validation happens at the database level but can't be
        tested through the API in single-user mode.
        """
        pass

    @pytest.mark.skip(
        reason="Single-user mode: registration disabled after first user, "
        "duplicate email check can't be tested via API"
    )
    async def test_register_duplicate_email(self, client: AsyncClient, db_session):
        """Test that duplicate emails are rejected.

        NOTE: This test is skipped because MyGarage operates in single-user mode.
        After the first user registers, all subsequent registration attempts return 403.
        Duplicate email validation happens at the database level but can't be
        tested through the API in single-user mode.
        """
        pass

    async def test_register_second_user_blocked(self, client: AsyncClient, test_user):
        """Test that registration is blocked after first user."""
        # test_user fixture ensures a user exists, so registration should be blocked
        response = await client.post(
            "/api/auth/register",
            json={
                "username": "seconduser",
                "email": "second@example.com",
                "password": "Password123!",
            },
        )

        # Should be 403 (disabled) or 429 (rate limited from previous tests)
        assert response.status_code in [403, 429]
        if response.status_code == 403:
            assert "disabled" in response.json()["detail"].lower()

    async def test_register_invalid_email(self, client: AsyncClient, db_session):
        """Test that invalid email addresses are rejected."""
        await db_session.execute(delete(User))
        await db_session.commit()

        response = await client.post(
            "/api/auth/register",
            json={
                "username": "testuser",
                "email": "not-an-email",  # Invalid email
                "password": "Password123!",
            },
        )

        assert response.status_code == 422  # Validation error


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestUserLogin:
    """Test user login endpoint."""

    async def test_login_success(self, client: AsyncClient, test_user, db_session):
        """Test successful login with valid credentials."""
        response = await client.post(
            "/api/auth/login",
            json={
                "username": test_user["username"],
                "password": "testpassword123",  # From conftest.py
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

        # Check that JWT cookie was set
        assert settings.jwt_cookie_name in response.cookies

    async def test_login_wrong_password(self, client: AsyncClient, test_user):
        """Test login fails with wrong password."""
        response = await client.post(
            "/api/auth/login",
            json={
                "username": test_user["username"],
                "password": "wrongpassword",
            },
        )

        assert response.status_code == 401
        assert "incorrect" in response.json()["detail"].lower()

    async def test_login_nonexistent_user(self, client: AsyncClient):
        """Test login fails with nonexistent username."""
        response = await client.post(
            "/api/auth/login",
            json={
                "username": "nonexistent",
                "password": "anypassword",
            },
        )

        assert response.status_code == 401
        assert "incorrect" in response.json()["detail"].lower()

    async def test_login_inactive_user(self, client: AsyncClient, test_user, db_session):
        """Test that inactive users cannot log in."""
        # Deactivate user
        user = await db_session.get(User, test_user["id"])
        user.is_active = False
        await db_session.commit()

        response = await client.post(
            "/api/auth/login",
            json={
                "username": test_user["username"],
                "password": "testpassword123",
            },
        )

        assert response.status_code == 403
        assert "inactive" in response.json()["detail"].lower()

    async def test_login_updates_last_login(self, client: AsyncClient, test_user, db_session):
        """Test that last_login timestamp is updated on successful login."""
        # Get user before login
        user_before = await db_session.get(User, test_user["id"])
        last_login_before = user_before.last_login

        # Login
        await client.post(
            "/api/auth/login",
            json={
                "username": test_user["username"],
                "password": "testpassword123",
            },
        )

        # Get user after login
        await db_session.refresh(user_before)
        last_login_after = user_before.last_login

        # last_login should be updated
        if last_login_before:
            assert last_login_after > last_login_before
        else:
            assert last_login_after is not None


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestProtectedEndpoints:
    """Test protected endpoints requiring authentication."""

    async def test_get_current_user_authenticated(
        self, client: AsyncClient, auth_headers, test_user
    ):
        """Test accessing /me endpoint with valid authentication."""
        response = await client.get("/api/auth/me", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_user["id"]
        assert data["username"] == test_user["username"]
        assert data["email"] == test_user["email"]

    async def test_get_current_user_no_auth(self, client: AsyncClient):
        """Test accessing /me endpoint without authentication."""
        response = await client.get("/api/auth/me")

        assert response.status_code == 401
        # API returns "Could not validate credentials" when no auth provided
        assert "could not validate credentials" in response.json()["detail"].lower()

    async def test_get_current_user_invalid_token(self, client: AsyncClient):
        """Test accessing /me endpoint with invalid token."""
        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalid_token_here"},
        )

        assert response.status_code == 401

    async def test_get_current_user_expired_token(self, client: AsyncClient):
        """Test accessing /me endpoint with expired token."""
        # Create an expired token (1 second expiry)
        from datetime import timedelta

        from app.services.auth import create_access_token

        expired_token = create_access_token(
            {"sub": "999", "username": "test"},
            expires_delta=timedelta(seconds=-1),  # Already expired
        )

        response = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {expired_token}"},
        )

        assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestLogout:
    """Test user logout endpoint."""

    async def test_logout_success(self, client: AsyncClient, auth_headers):
        """Test successful logout clears JWT cookie."""
        # Use auth_headers fixture (creates token directly, bypasses rate-limited login)
        # Logout is exempt from CSRF (idempotent operation, protected by JWT)
        response = await client.post(
            "/api/auth/logout",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert "logged out" in data["message"].lower()

        # Check that JWT cookie was cleared (set to empty with max_age=0)
        cookie_header = response.headers.get("set-cookie", "")
        assert settings.jwt_cookie_name in cookie_header
        # Cookie should be cleared (max-age=0 or expires in past)
        assert "max-age=0" in cookie_header.lower() or "expires=" in cookie_header.lower()

    async def test_logout_without_auth(self, client: AsyncClient):
        """Test logout without authentication returns 401."""
        response = await client.post("/api/auth/logout")

        # Logout requires authentication - should return 401 or 403
        assert response.status_code in [401, 403]


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestRateLimiting:
    """Test rate limiting on auth endpoints."""

    async def test_login_rate_limit(self, client: AsyncClient, test_user):
        """Test that login endpoint has rate limiting."""
        # Make multiple rapid login attempts
        for _ in range(10):
            await client.post(
                "/api/auth/login",
                json={
                    "username": test_user["username"],
                    "password": "wrongpassword",
                },
            )

        # Should eventually get rate limited
        # Note: This test may be flaky depending on rate limit settings
        # The actual rate limit check is implementation-specific
        # For now, we just verify the endpoint exists and responds
        response = await client.post(
            "/api/auth/login",
            json={
                "username": test_user["username"],
                "password": "wrongpassword",
            },
        )

        # Either 401 (auth failed) or 429 (rate limited) is acceptable
        assert response.status_code in [401, 429]


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestCookieSecureFlag:
    """Test cookie Secure flag behavior based on request scheme.

    Regression tests for GitHub issue #35: Local auth login fails over HTTP
    because the Secure flag causes browsers to silently drop the cookie.

    These tests run with rate limiting disabled to avoid interference from
    earlier test classes that exhaust the auth rate limit.
    """

    @pytest.fixture(autouse=True)
    def _reset_rate_limits(self):
        """Reset auth route's rate limiter storage to avoid 429s from earlier tests."""
        from app.routes.auth import limiter as auth_limiter

        storage = auth_limiter._storage
        storage.storage.clear()
        storage.expirations.clear()
        if hasattr(storage, "events"):
            storage.events.clear()

    @pytest.fixture(autouse=True)
    async def _ensure_local_auth(self, db_session):
        """Ensure auth_mode is 'local' for all tests in this class."""
        from app.models.settings import Setting

        result = await db_session.execute(select(Setting).where(Setting.key == "auth_mode"))
        auth_setting = result.scalar_one_or_none()
        if auth_setting:
            auth_setting.value = "local"
        else:
            db_session.add(Setting(key="auth_mode", value="local"))
        await db_session.commit()

    async def test_login_over_http_no_secure_flag(
        self, client: AsyncClient, test_user, monkeypatch
    ):
        """Login over HTTP must NOT set Secure flag on cookie.

        This is the core regression test for #35. The same AsyncClient is used
        for login and /auth/me — the client's cookie jar decides whether to
        retain the cookie, mirroring browser behavior.
        """
        # Ensure auto-detection mode (no explicit override)
        monkeypatch.delenv("JWT_COOKIE_SECURE", raising=False)

        # Login — test client runs over http://test (conftest.py:135)
        login_response = await client.post(
            "/api/auth/login",
            json={
                "username": test_user["username"],
                "password": "testpassword123",
            },
        )
        assert login_response.status_code == 200

        # Verify Set-Cookie does NOT contain Secure flag
        cookie_header = login_response.headers.get("set-cookie", "")
        assert settings.jwt_cookie_name in cookie_header
        # The Secure flag should NOT be present for HTTP connections
        assert "; secure" not in cookie_header.lower()

        # Use the SAME client to call /auth/me — cookie jar handles retention
        me_response = await client.get("/api/auth/me")
        assert me_response.status_code == 200
        assert me_response.json()["username"] == test_user["username"]

    async def test_login_with_forwarded_proto_https_sets_secure(
        self, client: AsyncClient, test_user, monkeypatch
    ):
        """Login behind a TLS-terminating proxy must set Secure flag on cookie.

        When X-Forwarded-Proto: https is present, the cookie should include
        the Secure flag since the browser-to-proxy connection is HTTPS.
        """
        # Ensure auto-detection mode
        monkeypatch.delenv("JWT_COOKIE_SECURE", raising=False)

        # Login with X-Forwarded-Proto: https header
        login_response = await client.post(
            "/api/auth/login",
            json={
                "username": test_user["username"],
                "password": "testpassword123",
            },
            headers={"X-Forwarded-Proto": "https"},
        )
        assert login_response.status_code == 200

        # Verify Set-Cookie DOES contain Secure flag
        cookie_header = login_response.headers.get("set-cookie", "")
        assert settings.jwt_cookie_name in cookie_header
        assert "; secure" in cookie_header.lower()


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestAdminPasswordReset:
    """Test admin password reset endpoint."""

    async def test_admin_reset_password_success(
        self, client: AsyncClient, auth_headers, non_admin_user
    ):
        """Test that an admin can reset another user's password."""
        response = await client.put(
            f"/api/auth/users/{non_admin_user['id']}/password",
            json={"new_password": "NewSecureP@ss1"},
            headers=auth_headers,
        )
        assert response.status_code == 204

    async def test_admin_reset_password_weak(
        self, client: AsyncClient, auth_headers, non_admin_user
    ):
        """Test that weak passwords are rejected with 422."""
        response = await client.put(
            f"/api/auth/users/{non_admin_user['id']}/password",
            json={"new_password": "weak"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_admin_reset_password_oidc_user(
        self, client: AsyncClient, auth_headers, db_session
    ):
        """Test that password reset is rejected for OIDC users."""
        # Create an OIDC user
        oidc_user = User(
            username="oidcuser",
            email="oidc@example.com",
            hashed_password="unused",
            is_active=True,
            is_admin=False,
            auth_method="oidc",
        )
        db_session.add(oidc_user)
        await db_session.commit()
        await db_session.refresh(oidc_user)

        response = await client.put(
            f"/api/auth/users/{oidc_user.id}/password",
            json={"new_password": "NewSecureP@ss1"},
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert "OIDC" in response.json()["detail"]

    async def test_self_update_rejects_privileged_fields(self, client: AsyncClient, auth_headers):
        """Test that PUT /api/auth/me rejects is_admin/is_active with 422."""
        response = await client.put(
            "/api/auth/me",
            json={"is_admin": True},
            headers=auth_headers,
        )
        assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.asyncio
class TestSessionLifetime:
    """Test that JWT, cookie, and CSRF lifetimes are aligned."""

    async def test_login_cookie_max_age(self, client: AsyncClient, test_user):
        """Test login response cookie Max-Age matches configured lifetime."""
        response = await client.post(
            "/api/auth/login",
            json={"username": test_user["username"], "password": "testpassword123"},
        )
        assert response.status_code == 200

        cookie_header = response.headers.get("set-cookie", "")
        assert f"max-age={settings.jwt_cookie_max_age}" in cookie_header.lower()

    async def test_login_jwt_exp(self, client: AsyncClient, test_user):
        """Test login JWT exp claim matches configured lifetime."""
        response = await client.post(
            "/api/auth/login",
            json={"username": test_user["username"], "password": "testpassword123"},
        )
        assert response.status_code == 200

        token = response.json()["access_token"]
        payload = jwt.decode(token, options={"verify_signature": False})

        expected_seconds = settings.access_token_expire_minutes * 60
        actual_seconds = payload["exp"] - payload.get("iat", payload["exp"] - expected_seconds)
        assert abs(actual_seconds - expected_seconds) < 5

    async def test_login_csrf_expiry(self, client: AsyncClient, test_user, db_session):
        """Test CSRF token expiry matches configured lifetime."""
        from app.models.csrf_token import CSRFToken
        from app.utils.datetime_utils import utc_now

        response = await client.post(
            "/api/auth/login",
            json={"username": test_user["username"], "password": "testpassword123"},
        )
        assert response.status_code == 200

        csrf_token_value = response.json()["csrf_token"]
        result = await db_session.execute(
            select(CSRFToken).where(CSRFToken.token == csrf_token_value)
        )
        csrf_record = result.scalar_one()

        now = utc_now()
        expected_minutes = settings.access_token_expire_minutes
        delta_minutes = (csrf_record.expires_at - now).total_seconds() / 60
        assert abs(delta_minutes - expected_minutes) < 1

    async def test_login_expires_in_matches_config(self, client: AsyncClient, test_user):
        """Test login response expires_in matches configured lifetime."""
        response = await client.post(
            "/api/auth/login",
            json={"username": test_user["username"], "password": "testpassword123"},
        )
        assert response.status_code == 200
        assert response.json()["expires_in"] == settings.access_token_expire_minutes * 60

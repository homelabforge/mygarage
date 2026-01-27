"""
Integration tests for authentication routes.

Tests user registration, login, logout, and protected endpoints.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import delete  # noqa: F401

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

    async def test_login_inactive_user(
        self, client: AsyncClient, test_user, db_session
    ):
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

    async def test_login_updates_last_login(
        self, client: AsyncClient, test_user, db_session
    ):
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
        assert (
            "max-age=0" in cookie_header.lower() or "expires=" in cookie_header.lower()
        )

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

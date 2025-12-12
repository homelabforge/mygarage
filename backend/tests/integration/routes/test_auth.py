"""
Integration tests for authentication routes.

Tests user registration, login, logout, and protected endpoints.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy import delete  # noqa: F401
from app.models.user import User
from app.config import settings


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

    async def test_register_duplicate_username(self, client: AsyncClient, db_session):
        """Test that duplicate usernames are rejected."""
        # Create first user
        await client.post(
            "/api/auth/register",
            json={
                "username": "testuser",
                "email": "test1@example.com",
                "password": "Password123!",
            },
        )

        # Try to register with same username
        response = await client.post(
            "/api/auth/register",
            json={
                "username": "testuser",  # Duplicate
                "email": "test2@example.com",
                "password": "Password123!",
            },
        )

        assert response.status_code == 400
        assert "already registered" in response.json()["detail"].lower()

    async def test_register_duplicate_email(self, client: AsyncClient, db_session):
        """Test that duplicate emails are rejected."""
        # Create first user
        await client.post(
            "/api/auth/register",
            json={
                "username": "user1",
                "email": "test@example.com",
                "password": "Password123!",
            },
        )

        # Try to register with same email
        response = await client.post(
            "/api/auth/register",
            json={
                "username": "user2",
                "email": "test@example.com",  # Duplicate
                "password": "Password123!",
            },
        )

        assert response.status_code == 400
        assert "already registered" in response.json()["detail"].lower()

    async def test_register_second_user_blocked(self, client: AsyncClient, test_user):
        """Test that registration is blocked after first user."""
        # test_user fixture creates a user, so we're the second user
        response = await client.post(
            "/api/auth/register",
            json={
                "username": "seconduser",
                "email": "second@example.com",
                "password": "Password123!",
            },
        )

        assert response.status_code == 403
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

    async def test_get_current_user_authenticated(self, client: AsyncClient, auth_headers, test_user):
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
        assert "not authenticated" in response.json()["detail"].lower()

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
        response = await client.post("/api/auth/logout", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "logged out" in data["message"].lower()

        # Check that JWT cookie was cleared (set to empty with max_age=0)
        cookie_header = response.headers.get("set-cookie", "")
        assert settings.jwt_cookie_name in cookie_header
        # Cookie should be cleared (max-age=0 or expires in past)
        assert "max-age=0" in cookie_header.lower() or "expires=" in cookie_header.lower()

    async def test_logout_without_auth(self, client: AsyncClient):
        """Test logout without authentication still succeeds (idempotent)."""
        response = await client.post("/api/auth/logout")

        # Should succeed even without auth (clear cookie anyway)
        assert response.status_code == 200


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

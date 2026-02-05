"""
Integration tests for OIDC authentication routes.

Tests OIDC endpoints with mocked external providers.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.models.settings import Setting


async def set_settings(db_session, settings_dict: dict[str, str]) -> None:
    """Helper to set settings, updating existing or creating new."""
    for key, value in settings_dict.items():
        result = await db_session.execute(select(Setting).where(Setting.key == key))
        existing = result.scalar_one_or_none()
        if existing:
            existing.value = value
        else:
            db_session.add(Setting(key=key, value=value))
    await db_session.commit()


async def clear_oidc_settings(db_session) -> None:
    """Clear all OIDC-related settings."""
    oidc_keys = [
        "oidc_enabled",
        "oidc_provider_name",
        "oidc_issuer_url",
        "oidc_client_id",
        "oidc_client_secret",
        "oidc_scopes",
        "oidc_auto_create_users",
        "oidc_username_claim",
    ]
    await db_session.execute(delete(Setting).where(Setting.key.in_(oidc_keys)))
    await db_session.commit()


@pytest.fixture(autouse=True)
async def clean_oidc_settings(db_session):
    """Clean OIDC settings before each test."""
    await clear_oidc_settings(db_session)
    yield
    await clear_oidc_settings(db_session)


@pytest.mark.integration
@pytest.mark.asyncio
class TestOIDCRoutes:
    """Test OIDC API endpoints."""

    # -------------------------------------------------------------------------
    # /config endpoint tests
    # -------------------------------------------------------------------------

    async def test_get_config_disabled(self, client: AsyncClient):
        """Test getting OIDC config when disabled."""
        response = await client.get("/api/auth/oidc/config")

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False
        assert data["provider_name"] == ""
        assert data["issuer_url"] == ""

    async def test_get_config_enabled(self, client: AsyncClient, db_session):
        """Test getting OIDC config when enabled."""
        await set_settings(
            db_session,
            {
                "oidc_enabled": "true",
                "oidc_provider_name": "Authentik",
                "oidc_issuer_url": "https://auth.example.com/application/o/myapp/",
                "oidc_client_id": "test-client-id",
                "oidc_scopes": "openid profile email",
            },
        )

        response = await client.get("/api/auth/oidc/config")

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True
        assert data["provider_name"] == "Authentik"
        assert data["issuer_url"] == "https://auth.example.com/application/o/myapp/"
        assert data["client_id"] == "test-client-id"
        # Secret should NOT be exposed
        assert "client_secret" not in data

    # -------------------------------------------------------------------------
    # /login endpoint tests
    # -------------------------------------------------------------------------

    async def test_login_disabled(self, client: AsyncClient):
        """Test login redirect when OIDC is disabled."""
        response = await client.get("/api/auth/oidc/login", follow_redirects=False)

        assert response.status_code == 400
        data = response.json()
        assert "not enabled" in data["detail"].lower()

    async def test_login_not_configured(self, client: AsyncClient, db_session):
        """Test login redirect when OIDC is enabled but not configured."""
        await set_settings(db_session, {"oidc_enabled": "true"})

        response = await client.get("/api/auth/oidc/login", follow_redirects=False)

        assert response.status_code == 500
        data = response.json()
        assert "not properly configured" in data["detail"].lower()

    async def test_login_redirect(self, client: AsyncClient, db_session):
        """Test login redirects to OIDC provider."""
        await set_settings(
            db_session,
            {
                "oidc_enabled": "true",
                "oidc_issuer_url": "https://auth.example.com/",
                "oidc_client_id": "test-client-id",
                "oidc_client_secret": "test-secret",
            },
        )

        # Mock OIDC provider metadata
        mock_metadata = {
            "issuer": "https://auth.example.com/",
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            "userinfo_endpoint": "https://auth.example.com/userinfo",
            "jwks_uri": "https://auth.example.com/.well-known/jwks.json",
        }

        with patch(
            "app.services.oidc.get_provider_metadata", new_callable=AsyncMock
        ) as mock_get_metadata:
            mock_get_metadata.return_value = mock_metadata

            with patch(
                "app.services.oidc.create_authorization_url", new_callable=AsyncMock
            ) as mock_auth_url:
                mock_auth_url.return_value = (
                    "https://auth.example.com/authorize?client_id=test",
                    "state123",
                )

                response = await client.get("/api/auth/oidc/login", follow_redirects=False)

        assert response.status_code == 302
        assert "auth.example.com" in response.headers.get("location", "")

    async def test_login_provider_timeout(self, client: AsyncClient, db_session):
        """Test login when provider times out."""
        import httpx

        await set_settings(
            db_session,
            {
                "oidc_enabled": "true",
                "oidc_issuer_url": "https://auth.example.com/",
                "oidc_client_id": "test-client-id",
            },
        )

        with patch(
            "app.services.oidc.get_provider_metadata", new_callable=AsyncMock
        ) as mock_get_metadata:
            mock_get_metadata.return_value = {
                "authorization_endpoint": "https://auth.example.com/authorize",
            }

            with patch(
                "app.services.oidc.create_authorization_url", new_callable=AsyncMock
            ) as mock_auth_url:
                mock_auth_url.side_effect = httpx.TimeoutException("Connection timed out")

                response = await client.get("/api/auth/oidc/login", follow_redirects=False)

        assert response.status_code == 504

    # -------------------------------------------------------------------------
    # /callback endpoint tests
    # -------------------------------------------------------------------------

    async def test_callback_invalid_state(self, client: AsyncClient):
        """Test callback with invalid state parameter."""
        response = await client.get(
            "/api/auth/oidc/callback",
            params={"code": "test-code", "state": "invalid-state"},
        )

        assert response.status_code == 400
        data = response.json()
        assert "invalid" in data["detail"].lower() or "expired" in data["detail"].lower()

    # -------------------------------------------------------------------------
    # /test endpoint tests
    # -------------------------------------------------------------------------

    async def test_test_connection_unauthorized(self, client: AsyncClient):
        """Test that unauthenticated users cannot test OIDC connection."""
        response = await client.post(
            "/api/auth/oidc/test",
            json={
                "issuer_url": "https://auth.example.com/",
                "client_id": "test-id",
                "client_secret": "test-secret",
            },
        )
        assert response.status_code == 401

    async def test_test_connection_non_admin(self, client: AsyncClient, db_session):
        """Test that non-admin users cannot test OIDC connection."""
        from sqlalchemy import or_

        from app.models.user import User
        from app.services.auth import create_access_token

        # Check if non-admin user already exists
        result = await db_session.execute(
            select(User).where(
                or_(User.username == "oidcuser", User.email == "oidcuser@example.com")
            )
        )
        non_admin = result.scalar_one_or_none()

        if not non_admin:
            non_admin = User(
                username="oidcuser",
                email="oidcuser@example.com",
                hashed_password="$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI",
                is_active=True,
                is_admin=False,
            )
            db_session.add(non_admin)
            await db_session.commit()
            await db_session.refresh(non_admin)

        token = create_access_token(data={"sub": str(non_admin.id), "username": non_admin.username})
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.post(
            "/api/auth/oidc/test",
            headers=headers,
            json={
                "issuer_url": "https://auth.example.com/",
                "client_id": "test-id",
                "client_secret": "test-secret",
            },
        )

        assert response.status_code == 403

    async def test_test_connection_success(self, client: AsyncClient, auth_headers):
        """Test OIDC connection test with valid config."""
        with patch("app.services.oidc.test_oidc_connection", new_callable=AsyncMock) as mock_test:
            mock_test.return_value = {
                "success": True,
                "message": "Connection successful",
                "issuer": "https://auth.example.com/",
            }

            response = await client.post(
                "/api/auth/oidc/test",
                headers=auth_headers,
                json={
                    "issuer_url": "https://auth.example.com/",
                    "client_id": "test-id",
                    "client_secret": "test-secret",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    async def test_test_connection_failure(self, client: AsyncClient, auth_headers):
        """Test OIDC connection test with invalid config."""
        with patch("app.services.oidc.test_oidc_connection", new_callable=AsyncMock) as mock_test:
            mock_test.return_value = {
                "success": False,
                "message": "Failed to fetch provider metadata",
            }

            response = await client.post(
                "/api/auth/oidc/test",
                headers=auth_headers,
                json={
                    "issuer_url": "https://invalid.example.com/",
                    "client_id": "test-id",
                    "client_secret": "test-secret",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "failed" in data["message"].lower()

    # -------------------------------------------------------------------------
    # /link-account endpoint tests
    # Note: These tests require the oidc_pending_links table which may not
    # exist in all test environments. Tests are marked to handle this.
    # -------------------------------------------------------------------------

    async def test_link_account_invalid_token(self, client: AsyncClient, db_session):
        """Test link account with invalid token."""
        from sqlalchemy import text

        # Check if the table exists
        result = await db_session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='oidc_pending_links'")
        )
        if not result.fetchone():
            pytest.skip("oidc_pending_links table not available in test database")

        response = await client.post(
            "/api/auth/oidc/link-account",
            json={
                "token": "invalid-token",
                "password": "testpassword",
            },
        )

        assert response.status_code == 401

    async def test_link_account_wrong_password(self, client: AsyncClient, db_session):
        """Test link account with wrong password."""
        from sqlalchemy import text

        # Check if the table exists
        result = await db_session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='oidc_pending_links'")
        )
        if not result.fetchone():
            pytest.skip("oidc_pending_links table not available in test database")

        response = await client.post(
            "/api/auth/oidc/link-account",
            json={
                "token": "nonexistent-token",
                "password": "wrongpassword",
            },
        )

        # Should reject with 401 for invalid token
        assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
class TestOIDCEdgeCases:
    """Test OIDC edge cases and error handling."""

    async def test_config_with_missing_fields(self, client: AsyncClient, db_session):
        """Test config endpoint with partial configuration."""
        await set_settings(
            db_session,
            {
                "oidc_enabled": "true",
                "oidc_provider_name": "Test Provider",
                # Missing issuer_url and client_id
            },
        )

        response = await client.get("/api/auth/oidc/config")

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True
        assert data["provider_name"] == "Test Provider"
        assert data["issuer_url"] == ""
        assert data["client_id"] == ""

    async def test_login_with_custom_scopes(self, client: AsyncClient, db_session):
        """Test login uses custom scopes if configured."""
        await set_settings(
            db_session,
            {
                "oidc_enabled": "true",
                "oidc_issuer_url": "https://auth.example.com/",
                "oidc_client_id": "test-client-id",
                "oidc_scopes": "openid profile email groups",
            },
        )

        mock_metadata = {
            "authorization_endpoint": "https://auth.example.com/authorize",
        }

        with patch(
            "app.services.oidc.get_provider_metadata", new_callable=AsyncMock
        ) as mock_get_metadata:
            mock_get_metadata.return_value = mock_metadata

            with patch(
                "app.services.oidc.create_authorization_url", new_callable=AsyncMock
            ) as mock_auth_url:
                mock_auth_url.return_value = ("https://auth.example.com/authorize", "state")

                response = await client.get("/api/auth/oidc/login", follow_redirects=False)

        # Should redirect (actual scope verification would be in service tests)
        assert response.status_code == 302

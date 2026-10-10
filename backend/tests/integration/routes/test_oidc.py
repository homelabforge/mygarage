"""
Integration tests for OIDC authentication routes.

Tests OIDC endpoints with mocked external providers.

The login start and the callback are full-page navigations, so a failure at
either sends the browser to `/login?sso_error=<code>` instead of a page of raw
JSON.
"""

import logging
from collections.abc import Iterator
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from httpx import AsyncClient
from joserfc.errors import JoseError
from sqlalchemy import delete, select

from app.models.settings import Setting
from app.routes import oidc as oidc_routes
from app.routes.oidc import limiter as oidc_route_limiter
from tests.integration._oidc_refusals import assert_sent_to_login


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
        "oidc_redirect_uri",
        "oidc_scopes",
        "oidc_auto_create_users",
        "oidc_username_claim",
    ]
    await db_session.execute(delete(Setting).where(Setting.key.in_(oidc_keys)))
    await db_session.commit()


def route_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The WARNING-and-up messages the OIDC routes logged."""
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == "app.routes.oidc" and r.levelno >= logging.WARNING
    ]


ENABLED = {
    "oidc_enabled": "true",
    "oidc_issuer_url": "https://auth.example.com/",
    "oidc_client_id": "test-client-id",
}


@pytest.fixture(autouse=True)
async def clean_oidc_settings(db_session):
    """Clean OIDC settings before each test."""
    await clear_oidc_settings(db_session)
    yield
    await clear_oidc_settings(db_session)


@pytest.fixture(autouse=True)
def _fresh_sso_limits() -> Iterator[None]:
    """The SSO routes allow 5 a minute per address, and this file starts SSO more often."""
    oidc_route_limiter.reset()
    yield
    oidc_route_limiter.reset()


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

    async def test_login_disabled(self, client: AsyncClient, caplog: pytest.LogCaptureFixture):
        """Login with OIDC off goes back to the login page, and leaves a trace in the log."""
        caplog.set_level(logging.WARNING, logger="app.routes.oidc")

        response = await client.get("/api/auth/oidc/login", follow_redirects=False)

        assert_sent_to_login(response, "failed")
        assert len(route_warnings(caplog)) == 1

    async def test_login_not_configured(
        self, client: AsyncClient, db_session, caplog: pytest.LogCaptureFixture
    ):
        """Login with OIDC on but no issuer or client ID goes back to the login page."""
        caplog.set_level(logging.WARNING, logger="app.routes.oidc")
        await set_settings(db_session, {"oidc_enabled": "true"})

        response = await client.get("/api/auth/oidc/login", follow_redirects=False)

        assert_sent_to_login(response, "failed")
        assert len(route_warnings(caplog)) == 1

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
        location = response.headers.get("location", "")
        assert location.startswith("https://auth.example.com/")

    async def test_login_provider_timeout(self, client: AsyncClient, db_session):
        """Test login when provider times out."""
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

        assert_sent_to_login(response, "failed")

    @pytest.mark.parametrize(
        "error",
        [
            httpx.ConnectError("refused"),
            JoseError("bad key"),
            ValueError("bad config"),
            KeyError("authorization_endpoint"),
        ],
        ids=["connect", "jose", "value", "key"],
    )
    async def test_login_authorization_url_errors(
        self, client: AsyncClient, db_session, error: Exception
    ):
        """These were a 503, a 401 and two 500s of raw JSON."""
        await set_settings(db_session, ENABLED)

        with (
            patch(
                "app.services.oidc.get_provider_metadata",
                new_callable=AsyncMock,
                return_value={"authorization_endpoint": "https://auth.example.com/authorize"},
            ),
            patch(
                "app.services.oidc.create_authorization_url",
                new_callable=AsyncMock,
                side_effect=error,
            ),
        ):
            response = await client.get("/api/auth/oidc/login", follow_redirects=False)

        assert_sent_to_login(response, "failed")

    async def test_login_metadata_unavailable(self, client: AsyncClient, db_session):
        """Login with no provider metadata goes back to the login page as a failure."""
        await set_settings(db_session, ENABLED)

        with patch(
            "app.services.oidc.get_provider_metadata", new_callable=AsyncMock, return_value=None
        ):
            response = await client.get("/api/auth/oidc/login", follow_redirects=False)

        assert_sent_to_login(response, "failed")

    async def test_login_blocked_issuer(
        self, client: AsyncClient, db_session, monkeypatch: pytest.MonkeyPatch
    ):
        """The metadata service raises SSRFProtectionError for it; that was a 500."""
        monkeypatch.delenv("MYGARAGE_TRUSTED_HOSTS", raising=False)
        await set_settings(db_session, {**ENABLED, "oidc_issuer_url": "http://127.0.0.1:9000"})

        response = await client.get("/api/auth/oidc/login", follow_redirects=False)

        assert_sent_to_login(response, "failed")

    # -------------------------------------------------------------------------
    # /callback endpoint tests
    # -------------------------------------------------------------------------

    async def test_callback_invalid_state(self, client: AsyncClient):
        """An unknown or expired state goes back to the login page as expired."""
        response = await client.get(
            "/api/auth/oidc/callback",
            params={"code": "test-code", "state": "invalid-state"},
            follow_redirects=False,
        )

        assert_sent_to_login(response, "expired")

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
        """Test OIDC connection test returns canonical {ok, issuer, algorithms_supported}."""
        with patch("app.services.oidc.test_oidc_connection", new_callable=AsyncMock) as mock_test:
            mock_test.return_value = {
                "success": True,
                "provider_reachable": True,
                "metadata_valid": True,
                "endpoints_found": True,
                "errors": [],
                "metadata": {
                    "issuer": "https://auth.example.com",
                    "id_token_signing_alg_values_supported": ["EdDSA", "RS256"],
                },
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
        assert data["ok"] is True
        assert data["issuer"] == "https://auth.example.com"
        assert data["algorithms_supported"] == ["EdDSA", "RS256"]

    async def test_test_connection_failure(self, client: AsyncClient, auth_headers):
        """Test OIDC connection test failure returns canonical {ok: false, error, detail}."""
        with patch("app.services.oidc.test_oidc_connection", new_callable=AsyncMock) as mock_test:
            mock_test.return_value = {
                "success": False,
                "provider_reachable": False,
                "metadata_valid": False,
                "endpoints_found": False,
                "errors": ["Failed to fetch provider metadata"],
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
        assert data["ok"] is False
        assert data["error"] == "unreachable"
        assert "fetch provider metadata" in (data.get("detail") or "")

    async def test_test_connection_blocked_issuer(
        self, client: AsyncClient, auth_headers, monkeypatch: pytest.MonkeyPatch
    ):
        """A blocked issuer is a fixed hint naming the env var, not a 500 or the exception text."""
        monkeypatch.delenv("MYGARAGE_TRUSTED_HOSTS", raising=False)

        response = await client.post(
            "/api/auth/oidc/test",
            headers=auth_headers,
            json={
                "issuer_url": "http://127.0.0.1:9000",
                "client_id": "test-id",
                "client_secret": "test-secret",
            },
        )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["ok"] is False
        assert data["error"] == "unreachable"
        detail = data.get("detail") or ""
        assert "MYGARAGE_TRUSTED_HOSTS" in detail
        assert "127.0.0.1" not in detail

    @pytest.mark.parametrize(
        "issuer_url",
        [
            "auth.example.com",
            "ftp://auth.example.com",
            "https:///realms/mygarage",
            "https://[auth.example.com",
        ],
        ids=["no-scheme", "ftp", "no-host", "unparseable"],
    )
    async def test_test_connection_issuer_that_isnt_a_url(
        self,
        client: AsyncClient,
        auth_headers,
        monkeypatch: pytest.MonkeyPatch,
        issuer_url: str,
    ):
        """A malformed issuer asks for a full URL; trusting its host would never fix it."""
        # Already trusted, as an admin following the blocked hint would have it.
        monkeypatch.setenv("MYGARAGE_TRUSTED_HOSTS", "auth.example.com")

        response = await client.post(
            "/api/auth/oidc/test",
            headers=auth_headers,
            json={
                "issuer_url": issuer_url,
                "client_id": "test-id",
                "client_secret": "test-secret",
            },
        )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["ok"] is False
        assert data["error"] == "unreachable"
        detail = data.get("detail") or ""
        assert detail == "Issuer URL must be a full URL starting with https:// (or http://)."
        assert "MYGARAGE_TRUSTED_HOSTS" not in detail
        assert "auth.example.com" not in detail

    # -------------------------------------------------------------------------
    # /config/admin endpoint tests (dedicated admin OIDC config — plan §5.4)
    # -------------------------------------------------------------------------

    async def test_admin_get_config_masks_secret(
        self, client: AsyncClient, auth_headers, db_session
    ):
        """Admin GET returns canonical '********' when a client_secret is stored."""
        await set_settings(
            db_session,
            {
                "oidc_enabled": "true",
                "oidc_provider_name": "Authentik",
                "oidc_issuer_url": "https://auth.example.com",
                "oidc_client_id": "test-client-id",
                "oidc_client_secret": "real-stored-secret",
            },
        )

        response = await client.get("/api/auth/oidc/config/admin", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True
        assert data["client_id"] == "test-client-id"
        assert data["client_secret"] == "********"

    async def test_admin_get_config_empty_secret_returns_empty_string(
        self, client: AsyncClient, auth_headers, db_session
    ):
        """No stored secret → admin GET returns empty string, not placeholder."""
        await set_settings(db_session, {"oidc_client_secret": ""})
        response = await client.get("/api/auth/oidc/config/admin", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["client_secret"] == ""

    async def test_admin_put_preserves_secret_on_empty(
        self, client: AsyncClient, auth_headers, db_session
    ):
        """Admin PUT with empty client_secret preserves the stored secret (§5.4(2))."""
        await set_settings(db_session, {"oidc_client_secret": "preserved-secret"})

        payload = {
            "enabled": True,
            "provider_name": "Authentik",
            "issuer_url": "https://auth.example.com",
            "client_id": "test-id",
            "client_secret": "",
            "scopes": "openid profile email",
            "auto_create_users": True,
            "admin_group": "",
            "username_claim": "preferred_username",
            "email_claim": "email",
            "full_name_claim": "name",
        }
        response = await client.put(
            "/api/auth/oidc/config/admin", headers=auth_headers, json=payload
        )
        assert response.status_code == 200

        result = await db_session.execute(
            select(Setting).where(Setting.key == "oidc_client_secret")
        )
        stored = result.scalar_one().value
        assert stored == "preserved-secret"

    async def test_admin_put_strips_issuer_trailing_slash(
        self, client: AsyncClient, auth_headers, db_session
    ):
        """Admin PUT rstrips trailing slash on issuer_url (§5.4(1))."""
        payload = {
            "enabled": True,
            "provider_name": "Authentik",
            "issuer_url": "https://auth.example.com/auth/v1/",
            "client_id": "test-id",
            "client_secret": "secret",
            "scopes": "openid",
            "auto_create_users": True,
            "admin_group": "",
            "username_claim": "preferred_username",
            "email_claim": "email",
            "full_name_claim": "name",
        }
        response = await client.put(
            "/api/auth/oidc/config/admin", headers=auth_headers, json=payload
        )
        assert response.status_code == 200

        result = await db_session.execute(select(Setting).where(Setting.key == "oidc_issuer_url"))
        stored = result.scalar_one().value
        assert stored == "https://auth.example.com/auth/v1"

    async def test_admin_put_writes_new_secret(self, client: AsyncClient, auth_headers, db_session):
        """Admin PUT with a real client_secret writes it through."""
        payload = {
            "enabled": True,
            "provider_name": "Authentik",
            "issuer_url": "https://auth.example.com",
            "client_id": "test-id",
            "client_secret": "brand-new-secret",
            "scopes": "openid",
            "auto_create_users": False,
            "admin_group": "admins",
            "username_claim": "preferred_username",
            "email_claim": "email",
            "full_name_claim": "name",
        }
        response = await client.put(
            "/api/auth/oidc/config/admin", headers=auth_headers, json=payload
        )
        assert response.status_code == 200

        result = await db_session.execute(
            select(Setting).where(Setting.key == "oidc_client_secret")
        )
        assert result.scalar_one().value == "brand-new-secret"

    async def test_admin_config_reachable_when_auth_disabled(
        self, client: AsyncClient, db_session, set_auth_mode
    ):
        """auth_mode='none' must not lock the admin OIDC surface.

        Regression: the endpoint 401'd whenever ``get_current_admin_user``
        returned None (its documented auth-disabled signal), which made the
        Settings → System save — it PUTs this endpoint before the settings
        batch carrying ``auth_mode`` — fail outright. That left a bootstrap
        deadlock: enabling auth required being authenticated.
        """
        await set_auth_mode("none")

        get_response = await client.get("/api/auth/oidc/config/admin")
        assert get_response.status_code == 200

        payload = {
            "enabled": True,
            "provider_name": "Rauthy",
            "issuer_url": "https://auth.example.com/",
            "client_id": "bootstrap-id",
            "client_secret": "bootstrap-secret",
            "scopes": "openid profile email",
            "auto_create_users": True,
            "admin_group": "",
            "username_claim": "preferred_username",
            "email_claim": "email",
            "full_name_claim": "name",
        }
        put_response = await client.put("/api/auth/oidc/config/admin", json=payload)
        assert put_response.status_code == 200

        result = await db_session.execute(
            select(Setting).where(Setting.key == "oidc_client_secret")
        )
        assert result.scalar_one().value == "bootstrap-secret"

    # -------------------------------------------------------------------------
    # /link-account endpoint tests
    # The oidc_pending_links table is always present — created by
    # Base.metadata.create_all in conftest's init_test_db fixture.
    # -------------------------------------------------------------------------

    async def test_link_account_invalid_token(self, client: AsyncClient, db_session):
        """Test link account with invalid token."""
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


PINNED = "https://pinned.example.com/api/auth/oidc/callback"
FORGED_HOST = {"Host": "evil.example.com", "X-Forwarded-Host": "evil.example.com"}


def admin_payload(**overrides: object) -> dict[str, object]:
    """A full admin PUT body, the way the SSO settings send it."""
    return {
        "enabled": True,
        "provider_name": "Rauthy",
        "issuer_url": "https://auth.example.com",
        "client_id": "test-client-id",
        "client_secret": "",
        "scopes": "openid profile email",
        "auto_create_users": True,
        "admin_group": "",
        "username_claim": "preferred_username",
        "email_claim": "email",
        "full_name_claim": "name",
        **overrides,
    }


async def stored_setting(db_session, key: str) -> str | None:
    """The stored value of one setting, or None with no row."""
    result = await db_session.execute(select(Setting.value).where(Setting.key == key))
    return result.scalar_one_or_none()


@pytest.mark.integration
@pytest.mark.asyncio
class TestAdminRedirectUri:
    """The SSO settings can pin oidc_redirect_uri, which used to need the batch endpoint."""

    async def test_get_returns_the_stored_value(
        self, client: AsyncClient, auth_headers, db_session
    ) -> None:
        await set_settings(db_session, {"oidc_redirect_uri": PINNED})

        response = await client.get("/api/auth/oidc/config/admin", headers=auth_headers)

        assert response.status_code == 200, response.text
        assert response.json()["redirect_uri"] == PINNED

    async def test_put_stores_it_stripped(
        self, client: AsyncClient, auth_headers, db_session
    ) -> None:
        response = await client.put(
            "/api/auth/oidc/config/admin",
            headers=auth_headers,
            json=admin_payload(redirect_uri=f"  {PINNED}  "),
        )

        assert response.status_code == 200, response.text
        assert await stored_setting(db_session, "oidc_redirect_uri") == PINNED

    @pytest.mark.parametrize("blank", ["", "   "], ids=["empty", "spaces"])
    async def test_put_blank_clears_it(
        self, client: AsyncClient, auth_headers, db_session, blank: str
    ) -> None:
        """Back to building it from each request."""
        await set_settings(db_session, {"oidc_redirect_uri": PINNED})

        response = await client.put(
            "/api/auth/oidc/config/admin",
            headers=auth_headers,
            json=admin_payload(redirect_uri=blank),
        )

        assert response.status_code == 200, response.text
        assert await stored_setting(db_session, "oidc_redirect_uri") == ""

    async def test_put_without_it_keeps_a_value_pinned_through_the_batch_endpoint(
        self, client: AsyncClient, auth_headers, db_session
    ) -> None:
        """Control: this PUT never wrote it before, so an older client mustn't wipe it now."""
        batch = await client.post(
            "/api/settings/batch",
            headers=auth_headers,
            json={"settings": {"oidc_redirect_uri": PINNED}},
        )
        assert batch.status_code == 200, batch.text

        response = await client.put(
            "/api/auth/oidc/config/admin", headers=auth_headers, json=admin_payload()
        )

        assert response.status_code == 200, response.text
        assert await stored_setting(db_session, "oidc_redirect_uri") == PINNED

    @pytest.mark.parametrize(
        "bad",
        ["ftp://x", "not a url", "https://", "https://[garage.example.com"],
        ids=["ftp", "no-scheme", "no-host", "unparseable"],
    )
    async def test_put_refuses_anything_but_an_absolute_http_url(
        self, client: AsyncClient, auth_headers, db_session, bad: str
    ) -> None:
        """And writes nothing, not even the fields that were fine."""
        await set_settings(db_session, {"oidc_client_id": "before-id", "oidc_redirect_uri": PINNED})

        response = await client.put(
            "/api/auth/oidc/config/admin",
            headers=auth_headers,
            json=admin_payload(client_id="after-id", redirect_uri=bad),
        )

        assert response.status_code == 422, response.text
        assert response.json()["detail"] == "redirect_uri must be an absolute http(s) URL"
        assert await stored_setting(db_session, "oidc_client_id") == "before-id"
        assert await stored_setting(db_session, "oidc_redirect_uri") == PINNED

    async def test_a_stored_bad_value_still_reads(
        self, client: AsyncClient, auth_headers, db_session
    ) -> None:
        """The batch endpoint doesn't check it, so the GET mustn't 500 on what it stored."""
        await set_settings(db_session, {"oidc_redirect_uri": "not a url"})

        response = await client.get("/api/auth/oidc/config/admin", headers=auth_headers)

        assert response.status_code == 200, response.text
        assert response.json()["redirect_uri"] == "not a url"


def redirect_uri_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The route warnings about a blank oidc_redirect_uri."""
    return [m for m in route_warnings(caplog) if "oidc_redirect_uri" in m]


@pytest.mark.integration
@pytest.mark.asyncio
class TestBlankRedirectUriWarning:
    """A-15: with oidc_redirect_uri blank, the callback URL comes from the request's Host.

    That's a config problem, not a bug, so the login says so once per process.
    create_authorization_url runs for real, so each test also checks which
    redirect_uri actually went to the IdP.
    """

    @pytest.fixture(autouse=True)
    def _not_warned_yet(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(oidc_routes, "_warned_blank_redirect_uri", False)

    async def _login(self, client: AsyncClient, headers: dict[str, str] | None = None) -> str:
        """Start SSO and return the redirect_uri it sent to the IdP."""
        with patch(
            "app.services.oidc.get_provider_metadata",
            new_callable=AsyncMock,
            return_value={"authorization_endpoint": "https://auth.example.com/authorize"},
        ):
            response = await client.get(
                "/api/auth/oidc/login", headers=headers, follow_redirects=False
            )
        assert response.status_code == 302, response.text
        return parse_qs(urlsplit(response.headers["location"]).query)["redirect_uri"][0]

    @pytest.mark.parametrize("stored", [None, "", "   "], ids=["no-row", "empty", "spaces"])
    async def test_a_blank_setting_warns_on_the_first_login_only(
        self,
        client: AsyncClient,
        db_session,
        caplog: pytest.LogCaptureFixture,
        stored: str | None,
    ) -> None:
        """Spaces count as blank, same as the service's strip()."""
        caplog.set_level(logging.WARNING, logger="app.routes.oidc")
        extra = {} if stored is None else {"oidc_redirect_uri": stored}
        await set_settings(db_session, {**ENABLED, **extra})

        assert await self._login(client) == "http://test/api/auth/oidc/callback"
        assert len(redirect_uri_warnings(caplog)) == 1

        assert await self._login(client) == "http://test/api/auth/oidc/callback"
        assert len(redirect_uri_warnings(caplog)) == 1

    async def test_a_pinned_setting_never_warns(
        self, client: AsyncClient, db_session, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Control: nothing to warn about once the admin pins it."""
        caplog.set_level(logging.WARNING, logger="app.routes.oidc")
        pinned = "https://garage.example.com/api/auth/oidc/callback"
        await set_settings(db_session, {**ENABLED, "oidc_redirect_uri": pinned})

        assert await self._login(client) == pinned
        assert await self._login(client) == pinned
        assert redirect_uri_warnings(caplog) == []

    async def test_a_forged_host_picks_the_callback_while_blank(
        self, client: AsyncClient, db_session, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Control: with nothing pinned, the forged header does pick the callback."""
        caplog.set_level(logging.WARNING, logger="app.routes.oidc")
        await set_settings(db_session, ENABLED)

        sent = await self._login(client, FORGED_HOST)

        assert sent == "http://evil.example.com/api/auth/oidc/callback"
        assert len(redirect_uri_warnings(caplog)) == 1

    async def test_a_callback_url_pinned_in_the_settings_beats_a_forged_host(
        self,
        client: AsyncClient,
        auth_headers,
        db_session,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Pinned through the same PUT the SSO settings send."""
        caplog.set_level(logging.WARNING, logger="app.routes.oidc")
        response = await client.put(
            "/api/auth/oidc/config/admin",
            headers=auth_headers,
            json=admin_payload(redirect_uri=PINNED),
        )
        assert response.status_code == 200, response.text

        assert await self._login(client, FORGED_HOST) == PINNED
        assert redirect_uri_warnings(caplog) == []

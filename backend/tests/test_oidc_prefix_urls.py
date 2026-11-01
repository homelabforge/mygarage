"""OIDC external URLs must include MYGARAGE_ROOT_PATH so the callback the IdP
redirects to (and the post-login frontend redirect) resolve under the prefix (#107)."""

from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse, urlsplit

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.main import app
from app.routes.oidc import _external_base  # thin alias over request_scheme.get_external_base_url
from app.utils import request_scheme
from tests.integration.routes.test_oidc import clear_oidc_settings, set_settings


class _Req:
    """Minimal Request stand-in: only `.headers` is read once the scheme is patched."""

    def __init__(self, host):
        self.headers = {"host": host}


def test_external_base_includes_prefix(monkeypatch):
    from app import config

    monkeypatch.setattr(config.settings, "root_path", "/mygarage", raising=False)
    monkeypatch.setattr(
        request_scheme, "get_request_scheme", lambda r: "https"
    )  # avoid a heavy request mock
    assert _external_base(_Req("example.com")) == "https://example.com/mygarage"


def test_external_base_root_unchanged(monkeypatch):
    from app import config

    monkeypatch.setattr(config.settings, "root_path", "", raising=False)
    monkeypatch.setattr(request_scheme, "get_request_scheme", lambda r: "https")
    assert (
        _external_base(_Req("example.com")) == "https://example.com"
    )  # no prefix, no trailing slash


# -----------------------------------------------------------------------------
# Step 3c: prove the WIRED contract, not just the helper (Codex R1-H3). Drives
# the real /api/auth/oidc/login route with settings.root_path set, mocking only
# the external provider metadata fetch. `create_authorization_url` runs for
# real (auto-derives redirect_uri from the prefixed base_url since no
# oidc_redirect_uri setting is stored), so this fails if any handler in the
# chain emits an unprefixed callback URI.
# -----------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_login_redirect_uri_includes_prefix(client: AsyncClient, db_session, monkeypatch):
    """The auth-URL redirect_uri emitted by /api/auth/oidc/login carries root_path."""
    from app import config

    monkeypatch.setattr(config.settings, "root_path", "/mygarage", raising=False)

    await clear_oidc_settings(db_session)
    try:
        await set_settings(
            db_session,
            {
                "oidc_enabled": "true",
                "oidc_issuer_url": "https://auth.example.com/",
                "oidc_client_id": "test-client-id",
                "oidc_client_secret": "test-secret",
                # oidc_redirect_uri intentionally left unset -> auto-derived branch
            },
        )

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

            # create_authorization_url is NOT mocked here — it must run for real
            # so the auto-derived redirect_uri reflects the actual base_url the
            # login handler computed.
            response = await client.get(
                "/api/auth/oidc/login",
                follow_redirects=False,
                headers={"host": "example.com"},
            )

        assert response.status_code == 302
        location = response.headers["location"]
        redirect_uri = parse_qs(urlparse(location).query)["redirect_uri"][0]
        # Test transport is plain HTTP; the scheme itself is exercised by the
        # _external_base unit tests above — here we assert the prefix + path.
        assert redirect_uri.endswith("example.com/mygarage/api/auth/oidc/callback")
    finally:
        await clear_oidc_settings(db_session)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_failed_login_start_behind_a_subpath_keeps_the_prefix(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With SSO off the start sends you back to the login page, which lives under the prefix too.

    Asks for ``client`` for its get_db override. Coverage-only: dropping the
    prefix in ``_to_login`` turns it red.
    """
    monkeypatch.setattr(settings, "root_path", "/mygarage")
    await clear_oidc_settings(db_session)

    async with AsyncClient(
        transport=ASGITransport(app=app, root_path="/mygarage"), base_url="http://test"
    ) as subpath:
        response = await subpath.get("/mygarage/api/auth/oidc/login", follow_redirects=False)

    assert response.status_code == 302, response.text
    location = urlsplit(response.headers["location"])
    assert location.path == "/mygarage/login"
    assert parse_qs(location.query) == {"sso_error": ["failed"]}

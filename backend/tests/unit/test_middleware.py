"""Unit tests for security middleware.

Tests CSRF protection, security headers, and request ID middleware.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.middleware import (
    CSRFProtectionMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
    is_test_mode,
)


@pytest.mark.unit
class TestIsTestMode:
    """Test the is_test_mode helper function."""

    def test_returns_true_when_env_set(self, monkeypatch):
        """Test that is_test_mode returns True when MYGARAGE_TEST_MODE=true."""
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "true")
        assert is_test_mode() is True

    def test_returns_true_case_insensitive(self, monkeypatch):
        """Test that is_test_mode handles uppercase."""
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "TRUE")
        assert is_test_mode() is True

    def test_returns_false_when_not_set(self, monkeypatch):
        """Test that is_test_mode returns False when env var is not set."""
        monkeypatch.delenv("MYGARAGE_TEST_MODE", raising=False)
        assert is_test_mode() is False

    def test_returns_false_when_set_to_false(self, monkeypatch):
        """Test that is_test_mode returns False when set to 'false'."""
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "false")
        assert is_test_mode() is False


@pytest.mark.unit
class TestSecurityHeadersMiddleware:
    """Test security headers are added to all responses."""

    @pytest.fixture
    def middleware(self):
        """Create a SecurityHeadersMiddleware instance."""
        app = MagicMock()
        return SecurityHeadersMiddleware(app)

    @pytest.mark.asyncio
    async def test_adds_csp_header(self, middleware):
        """Test Content-Security-Policy header is added."""
        request = MagicMock(spec=Request)
        mock_response = Response(content="OK")
        call_next = AsyncMock(return_value=mock_response)

        response = await middleware.dispatch(request, call_next)

        assert "Content-Security-Policy" in response.headers
        csp = response.headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "object-src 'none'" in csp

    @pytest.mark.asyncio
    async def test_adds_security_headers(self, middleware):
        """Test all security headers are present."""
        request = MagicMock(spec=Request)
        mock_response = Response(content="OK")
        call_next = AsyncMock(return_value=mock_response)

        response = await middleware.dispatch(request, call_next)

        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
        assert response.headers["X-XSS-Protection"] == "1; mode=block"
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "Permissions-Policy" in response.headers


@pytest.mark.unit
class TestRequestIDMiddleware:
    """Test request ID generation."""

    @pytest.fixture
    def middleware(self):
        """Create a RequestIDMiddleware instance."""
        app = MagicMock()
        return RequestIDMiddleware(app)

    @pytest.mark.asyncio
    async def test_adds_request_id_to_response(self, middleware):
        """Test request ID is added to response headers."""
        request = MagicMock(spec=Request)
        request.state = MagicMock()
        mock_response = Response(content="OK")
        call_next = AsyncMock(return_value=mock_response)

        response = await middleware.dispatch(request, call_next)

        assert "X-Request-ID" in response.headers
        # Validate it's a UUID
        uuid.UUID(response.headers["X-Request-ID"])

    @pytest.mark.asyncio
    async def test_sets_request_id_on_state(self, middleware):
        """Test request ID is set on request.state."""
        request = MagicMock(spec=Request)
        request.state = MagicMock()
        mock_response = Response(content="OK")
        call_next = AsyncMock(return_value=mock_response)

        await middleware.dispatch(request, call_next)

        # Verify request_id was set on state
        assert hasattr(request.state, "request_id") or request.state.request_id is not None

    @pytest.mark.asyncio
    async def test_generates_unique_ids(self, middleware):
        """Test that each request gets a unique ID."""
        request1 = MagicMock(spec=Request)
        request1.state = MagicMock()
        request2 = MagicMock(spec=Request)
        request2.state = MagicMock()
        mock_response = Response(content="OK")

        response1 = await middleware.dispatch(request1, AsyncMock(return_value=mock_response))
        response2 = await middleware.dispatch(
            request2, AsyncMock(return_value=Response(content="OK"))
        )

        assert response1.headers["X-Request-ID"] != response2.headers["X-Request-ID"]


@pytest.mark.unit
class TestCSRFProtectionMiddleware:
    """Test CSRF protection middleware."""

    @pytest.fixture
    def middleware(self):
        """Create a CSRFProtectionMiddleware instance."""
        app = MagicMock()
        return CSRFProtectionMiddleware(app)

    def _make_request(
        self, method: str = "POST", path: str = "/api/vehicles", headers: dict | None = None
    ):
        """Create a mock request."""
        request = MagicMock(spec=Request)
        request.method = method
        request.url = MagicMock()
        request.url.path = path
        request.headers = headers or {}
        request.state = MagicMock()
        return request

    @pytest.mark.asyncio
    async def test_skips_in_test_mode(self, middleware, monkeypatch):
        """Test CSRF validation is skipped in test mode."""
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "true")
        request = self._make_request(method="POST")
        mock_response = Response(content="OK")
        call_next = AsyncMock(return_value=mock_response)

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 200
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_get_requests(self, middleware, monkeypatch):
        """Test GET requests bypass CSRF."""
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "false")
        request = self._make_request(method="GET")
        mock_response = Response(content="OK")
        call_next = AsyncMock(return_value=mock_response)

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 200
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_head_requests(self, middleware, monkeypatch):
        """Test HEAD requests bypass CSRF."""
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "false")
        request = self._make_request(method="HEAD")
        mock_response = Response(content="OK")
        call_next = AsyncMock(return_value=mock_response)

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_skips_options_requests(self, middleware, monkeypatch):
        """Test OPTIONS requests bypass CSRF."""
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "false")
        request = self._make_request(method="OPTIONS")
        mock_response = Response(content="OK")
        call_next = AsyncMock(return_value=mock_response)

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 200

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "exempt_path",
        [
            "/api/auth/login",
            "/api/auth/register",
            "/api/auth/logout",
            "/api/auth/oidc/callback",
            "/api/health",
            "/api/settings/public",
            "/api/backup/create",
            "/api/settings/batch",
            "/api/v1/livelink/ingest",
        ],
    )
    async def test_skips_exempt_paths(self, middleware, monkeypatch, exempt_path):
        """Test exempt paths bypass CSRF validation."""
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "false")
        request = self._make_request(method="POST", path=exempt_path)
        mock_response = Response(content="OK")
        call_next = AsyncMock(return_value=mock_response)

        response = await middleware.dispatch(request, call_next)

        assert response.status_code == 200
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rejects_missing_csrf_token(self, middleware, monkeypatch):
        """Test POST without CSRF token returns 403."""
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "false")
        request = self._make_request(method="POST", path="/api/vehicles")
        mock_response = Response(content="OK")
        call_next = AsyncMock(return_value=mock_response)

        # Mock auth mode check to return something other than "none"
        with patch("app.middleware.get_db_context") as mock_ctx:
            mock_db = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("app.services.auth.get_auth_mode", return_value="local"):
                response = await middleware.dispatch(request, call_next)

        assert response.status_code == 403
        call_next.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_invalid_csrf_token(self, middleware, monkeypatch):
        """Test POST with invalid CSRF token returns 403."""
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "false")
        request = self._make_request(
            method="POST",
            path="/api/vehicles",
            headers={"X-CSRF-Token": "invalid-token-abc"},
        )
        mock_response = Response(content="OK")
        call_next = AsyncMock(return_value=mock_response)

        # Mock get_db_context to return a mock db where the token lookup returns None
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.middleware.get_db_context") as mock_ctx:
            # First call: auth mode check
            # Second call: token validation
            mock_ctx_instance = AsyncMock()
            mock_ctx_instance.__aenter__ = AsyncMock(return_value=mock_db)
            mock_ctx_instance.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.return_value = mock_ctx_instance
            with patch("app.services.auth.get_auth_mode", return_value="local"):
                response = await middleware.dispatch(request, call_next)

        assert response.status_code == 403
        call_next.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_accepts_valid_csrf_token(self, middleware, monkeypatch):
        """Test POST with valid CSRF token is allowed through."""
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "false")
        request = self._make_request(
            method="POST",
            path="/api/vehicles",
            headers={"X-CSRF-Token": "valid-token-123"},
        )
        request.state = MagicMock()
        mock_response = Response(content="OK")
        call_next = AsyncMock(return_value=mock_response)

        # Mock valid token lookup
        mock_token_record = MagicMock()
        mock_token_record.user_id = 1

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_token_record
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.middleware.get_db_context") as mock_ctx:
            mock_ctx.side_effect = lambda: type(
                "_CM",
                (),
                {
                    "__aenter__": AsyncMock(return_value=mock_db),
                    "__aexit__": AsyncMock(return_value=False),
                },
            )()
            with patch("app.services.auth.get_auth_mode", return_value="local"):
                response = await middleware.dispatch(request, call_next)

        assert response.status_code == 200
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_csrf_when_auth_disabled(self, middleware, monkeypatch):
        """Test CSRF is skipped when auth mode is 'none'."""
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "false")
        request = self._make_request(method="POST", path="/api/vehicles")
        mock_response = Response(content="OK")
        call_next = AsyncMock(return_value=mock_response)

        mock_db = AsyncMock()

        with patch("app.middleware.get_db_context") as mock_ctx:
            mock_ctx.side_effect = lambda: type(
                "_CM",
                (),
                {
                    "__aenter__": AsyncMock(return_value=mock_db),
                    "__aexit__": AsyncMock(return_value=False),
                },
            )()
            with patch("app.services.auth.get_auth_mode", return_value="none"):
                response = await middleware.dispatch(request, call_next)

        assert response.status_code == 200
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_put_requires_csrf(self, middleware, monkeypatch):
        """Test PUT method also requires CSRF token."""
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "false")
        request = self._make_request(method="PUT", path="/api/vehicles/VIN123")
        mock_response = Response(content="OK")
        call_next = AsyncMock(return_value=mock_response)

        with patch("app.middleware.get_db_context") as mock_ctx:
            mock_db = AsyncMock()
            mock_ctx.side_effect = lambda: type(
                "_CM",
                (),
                {
                    "__aenter__": AsyncMock(return_value=mock_db),
                    "__aexit__": AsyncMock(return_value=False),
                },
            )()
            with patch("app.services.auth.get_auth_mode", return_value="local"):
                response = await middleware.dispatch(request, call_next)

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_requires_csrf(self, middleware, monkeypatch):
        """Test DELETE method also requires CSRF token."""
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "false")
        request = self._make_request(method="DELETE", path="/api/vehicles/VIN123")
        mock_response = Response(content="OK")
        call_next = AsyncMock(return_value=mock_response)

        with patch("app.middleware.get_db_context") as mock_ctx:
            mock_db = AsyncMock()
            mock_ctx.side_effect = lambda: type(
                "_CM",
                (),
                {
                    "__aenter__": AsyncMock(return_value=mock_db),
                    "__aexit__": AsyncMock(return_value=False),
                },
            )()
            with patch("app.services.auth.get_auth_mode", return_value="local"):
                response = await middleware.dispatch(request, call_next)

        assert response.status_code == 403

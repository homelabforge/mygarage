"""Unit tests for security middleware.

Tests CSRF protection, security headers, and request ID middleware.

The middleware are pure ASGI, not BaseHTTPMiddleware, so these tests
exercise the ASGI 3 interface directly with a small helper rather than
calling a `dispatch` method.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.middleware import (
    CSRFProtectionMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
    is_test_mode,
)


async def _ok_downstream(scope, receive, send):
    """Default downstream app: returns 200 OK with no body."""
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"OK"})


async def call_asgi(
    middleware,
    *,
    method: str = "POST",
    path: str = "/api/vehicles",
    headers: dict[str, str] | None = None,
) -> dict:
    """Invoke an ASGI middleware and return the captured response.

    Returns a dict with keys: status, headers (lowercased dict),
    body (bytes), downstream_called (bool), scope_state (mapping).
    """
    captured: dict = {
        "status": None,
        "headers": {},
        "body": b"",
        "downstream_called": False,
        "scope_state": None,
    }

    async def downstream(scope, receive, send):
        captured["downstream_called"] = True
        captured["scope_state"] = scope.get("state", {})
        await _ok_downstream(scope, receive, send)

    # The middleware was constructed against a fresh app placeholder in the
    # fixture; swap in our recording downstream for the duration of this call.
    original_app = middleware.app
    middleware.app = downstream
    try:
        encoded_headers = [
            (name.lower().encode("latin-1"), value.encode("latin-1"))
            for name, value in (headers or {}).items()
        ]
        scope = {
            "type": "http",
            "method": method,
            "path": path,
            "headers": encoded_headers,
            "query_string": b"",
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            if message["type"] == "http.response.start":
                captured["status"] = message["status"]
                captured["headers"] = {
                    k.decode("latin-1").lower(): v.decode("latin-1") for k, v in message["headers"]
                }
            elif message["type"] == "http.response.body":
                captured["body"] += message.get("body", b"")

        await middleware(scope, receive, send)
    finally:
        middleware.app = original_app

    return captured


@pytest.mark.unit
class TestIsTestMode:
    """Test the is_test_mode helper function."""

    def test_returns_true_when_env_set(self, monkeypatch):
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "true")
        assert is_test_mode() is True

    def test_returns_true_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "TRUE")
        assert is_test_mode() is True

    def test_returns_false_when_not_set(self, monkeypatch):
        monkeypatch.delenv("MYGARAGE_TEST_MODE", raising=False)
        assert is_test_mode() is False

    def test_returns_false_when_set_to_false(self, monkeypatch):
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "false")
        assert is_test_mode() is False


@pytest.mark.unit
class TestSecurityHeadersMiddleware:
    """Test security headers are added to all responses."""

    @pytest.fixture
    def middleware(self):
        return SecurityHeadersMiddleware(_ok_downstream)

    @pytest.mark.asyncio
    async def test_adds_csp_header(self, middleware):
        result = await call_asgi(middleware, method="GET", path="/")

        csp = result["headers"].get("content-security-policy", "")
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "object-src 'none'" in csp

    @pytest.mark.asyncio
    async def test_adds_security_headers(self, middleware):
        result = await call_asgi(middleware, method="GET", path="/")

        h = result["headers"]
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "SAMEORIGIN"
        assert h["x-xss-protection"] == "1; mode=block"
        assert h["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "permissions-policy" in h


@pytest.mark.unit
class TestRequestIDMiddleware:
    """Test request ID generation."""

    @pytest.fixture
    def middleware(self):
        return RequestIDMiddleware(_ok_downstream)

    @pytest.mark.asyncio
    async def test_adds_request_id_to_response(self, middleware):
        result = await call_asgi(middleware, method="GET", path="/")

        rid = result["headers"].get("x-request-id")
        assert rid is not None
        # validate it's a UUID
        uuid.UUID(rid)

    @pytest.mark.asyncio
    async def test_sets_request_id_on_scope_state(self, middleware):
        result = await call_asgi(middleware, method="GET", path="/")

        state = result["scope_state"]
        # state can be dict (our default) or a State instance
        rid = state["request_id"] if isinstance(state, dict) else state.request_id
        assert rid == result["headers"]["x-request-id"]

    @pytest.mark.asyncio
    async def test_generates_unique_ids(self, middleware):
        a = await call_asgi(middleware, method="GET", path="/")
        b = await call_asgi(middleware, method="GET", path="/")
        assert a["headers"]["x-request-id"] != b["headers"]["x-request-id"]


def _patch_auth_mode(value: str):
    """Patch both the auth-mode lookup and its DB context manager.

    The middleware enters a DB context purely to inspect auth_mode, so we
    swap the context manager for one that yields a dummy db and patch
    `get_auth_mode` to return the desired value.
    """
    mock_db = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return (
        patch("app.middleware.get_db_context", return_value=ctx),
        patch("app.services.auth.get_auth_mode", AsyncMock(return_value=value)),
    )


@pytest.mark.unit
class TestCSRFProtectionMiddleware:
    """Test CSRF protection middleware."""

    @pytest.fixture
    def middleware(self):
        return CSRFProtectionMiddleware(_ok_downstream)

    @pytest.mark.asyncio
    async def test_skips_in_test_mode(self, middleware, monkeypatch):
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "true")
        result = await call_asgi(middleware, method="POST", path="/api/vehicles")
        assert result["status"] == 200
        assert result["downstream_called"] is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
    async def test_skips_safe_methods(self, middleware, monkeypatch, method):
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "false")
        result = await call_asgi(middleware, method=method, path="/api/vehicles")
        assert result["status"] == 200
        assert result["downstream_called"] is True

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
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "false")
        result = await call_asgi(middleware, method="POST", path=exempt_path)
        assert result["status"] == 200
        assert result["downstream_called"] is True

    @pytest.mark.asyncio
    async def test_rejects_missing_csrf_token(self, middleware, monkeypatch):
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "false")
        ctx_patch, auth_patch = _patch_auth_mode("local")
        with ctx_patch, auth_patch:
            result = await call_asgi(middleware, method="POST", path="/api/vehicles")
        assert result["status"] == 403
        assert result["downstream_called"] is False
        assert b"CSRF token missing" in result["body"]

    @pytest.mark.asyncio
    async def test_rejects_invalid_csrf_token(self, middleware, monkeypatch):
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "false")
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.middleware.get_db_context", return_value=ctx),
            patch("app.services.auth.get_auth_mode", AsyncMock(return_value="local")),
        ):
            result = await call_asgi(
                middleware,
                method="POST",
                path="/api/vehicles",
                headers={"X-CSRF-Token": "invalid-token-abc"},
            )

        assert result["status"] == 403
        assert result["downstream_called"] is False
        assert b"Invalid or expired CSRF token" in result["body"]

    @pytest.mark.asyncio
    async def test_accepts_valid_csrf_token(self, middleware, monkeypatch):
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "false")
        token_record = MagicMock()
        token_record.user_id = 42
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = token_record
        mock_db.execute = AsyncMock(return_value=mock_result)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_db)
        ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.middleware.get_db_context", return_value=ctx),
            patch("app.services.auth.get_auth_mode", AsyncMock(return_value="local")),
        ):
            result = await call_asgi(
                middleware,
                method="POST",
                path="/api/vehicles",
                headers={"X-CSRF-Token": "valid-token-123"},
            )

        assert result["status"] == 200
        assert result["downstream_called"] is True
        state = result["scope_state"]
        validated_user_id = (
            state["csrf_validated_user_id"]
            if isinstance(state, dict)
            else state.csrf_validated_user_id
        )
        assert validated_user_id == 42

    @pytest.mark.asyncio
    async def test_skips_csrf_when_auth_disabled(self, middleware, monkeypatch):
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "false")
        ctx_patch, auth_patch = _patch_auth_mode("none")
        with ctx_patch, auth_patch:
            result = await call_asgi(middleware, method="POST", path="/api/vehicles")
        assert result["status"] == 200
        assert result["downstream_called"] is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH"])
    async def test_unsafe_methods_require_csrf(self, middleware, monkeypatch, method):
        monkeypatch.setenv("MYGARAGE_TEST_MODE", "false")
        ctx_patch, auth_patch = _patch_auth_mode("local")
        with ctx_patch, auth_patch:
            result = await call_asgi(middleware, method=method, path="/api/vehicles/VIN123")
        assert result["status"] == 403
        assert result["downstream_called"] is False

"""Unit tests for request scheme resolution utilities.

Tests get_request_scheme() and get_cookie_secure() from app.utils.request_scheme.
"""

from unittest.mock import MagicMock

import pytest

from app.utils.request_scheme import get_cookie_secure, get_request_scheme


def _make_request(scheme: str = "http", headers: dict[str, str] | None = None) -> MagicMock:
    """Create a mock FastAPI Request with the given scheme and headers."""
    request = MagicMock()
    request.url.scheme = scheme
    request.headers = headers or {}
    return request


@pytest.mark.unit
class TestGetRequestScheme:
    """Test get_request_scheme() scheme resolution."""

    def test_http_no_proxy_headers(self) -> None:
        """Plain HTTP request without proxy headers returns 'http'."""
        request = _make_request("http")
        assert get_request_scheme(request) == "http"

    def test_https_request(self) -> None:
        """Direct HTTPS request returns 'https'."""
        request = _make_request("https")
        assert get_request_scheme(request) == "https"

    def test_forwarded_proto_https(self) -> None:
        """X-Forwarded-Proto: https overrides HTTP scheme."""
        request = _make_request("http", {"x-forwarded-proto": "https"})
        assert get_request_scheme(request) == "https"

    def test_forwarded_proto_http(self) -> None:
        """X-Forwarded-Proto: http on HTTP request returns 'http'."""
        request = _make_request("http", {"x-forwarded-proto": "http"})
        assert get_request_scheme(request) == "http"

    def test_multi_value_forwarded_proto(self) -> None:
        """Comma-separated X-Forwarded-Proto takes first value (leftmost proxy)."""
        request = _make_request("http", {"x-forwarded-proto": "https, http"})
        assert get_request_scheme(request) == "https"

    def test_multi_value_first_is_http(self) -> None:
        """If first value is http, returns 'http' even if later values are https."""
        request = _make_request("http", {"x-forwarded-proto": "http, https"})
        assert get_request_scheme(request) == "http"

    def test_whitespace_and_casing(self) -> None:
        """Normalizes whitespace and casing."""
        request = _make_request("http", {"x-forwarded-proto": "  HTTPS  "})
        assert get_request_scheme(request) == "https"

    def test_garbage_value_falls_back_to_http(self) -> None:
        """Unrecognized X-Forwarded-Proto value resolves to 'http'."""
        request = _make_request("http", {"x-forwarded-proto": "ftp"})
        assert get_request_scheme(request) == "http"

    def test_empty_value_falls_back_to_scheme(self) -> None:
        """Empty X-Forwarded-Proto falls back to request.url.scheme."""
        request = _make_request("https", {"x-forwarded-proto": ""})
        # Empty string is falsy, so header is treated as absent
        assert get_request_scheme(request) == "https"

    def test_whitespace_only_value(self) -> None:
        """Whitespace-only X-Forwarded-Proto resolves to 'http'."""
        request = _make_request("https", {"x-forwarded-proto": "   "})
        # Non-empty string is truthy, but stripped value isn't "https"
        assert get_request_scheme(request) == "http"


@pytest.mark.unit
class TestGetCookieSecure:
    """Test get_cookie_secure() cookie Secure flag determination."""

    def test_explicit_env_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit JWT_COOKIE_SECURE=true returns True regardless of scheme."""
        monkeypatch.setenv("JWT_COOKIE_SECURE", "true")
        request = _make_request("http")
        assert get_cookie_secure(request) is True

    def test_explicit_env_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit JWT_COOKIE_SECURE=false returns False regardless of scheme."""
        monkeypatch.setenv("JWT_COOKIE_SECURE", "false")
        request = _make_request("https")
        assert get_cookie_secure(request) is False

    def test_explicit_env_yes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """JWT_COOKIE_SECURE=yes is treated as True."""
        monkeypatch.setenv("JWT_COOKIE_SECURE", "yes")
        request = _make_request("http")
        assert get_cookie_secure(request) is True

    def test_explicit_env_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """JWT_COOKIE_SECURE=0 is treated as False."""
        monkeypatch.setenv("JWT_COOKIE_SECURE", "0")
        request = _make_request("https")
        assert get_cookie_secure(request) is False

    def test_auto_mode_http(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Auto mode on HTTP returns False."""
        monkeypatch.delenv("JWT_COOKIE_SECURE", raising=False)
        request = _make_request("http")
        assert get_cookie_secure(request) is False

    def test_auto_mode_https(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Auto mode on HTTPS returns True."""
        monkeypatch.delenv("JWT_COOKIE_SECURE", raising=False)
        request = _make_request("https")
        assert get_cookie_secure(request) is True

    def test_auto_mode_http_with_forwarded_https(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Auto mode behind reverse proxy (X-Forwarded-Proto: https) returns True."""
        monkeypatch.delenv("JWT_COOKIE_SECURE", raising=False)
        request = _make_request("http", {"x-forwarded-proto": "https"})
        assert get_cookie_secure(request) is True

    def test_env_auto_value_falls_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """JWT_COOKIE_SECURE=auto falls through to scheme detection."""
        monkeypatch.setenv("JWT_COOKIE_SECURE", "auto")
        request = _make_request("http")
        assert get_cookie_secure(request) is False

    def test_env_unrecognized_value_falls_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unrecognized JWT_COOKIE_SECURE value falls through to scheme detection."""
        monkeypatch.setenv("JWT_COOKIE_SECURE", "maybe")
        request = _make_request("https")
        assert get_cookie_secure(request) is True

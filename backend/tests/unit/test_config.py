"""Unit tests for Settings configuration and derivation."""

import pytest
from pydantic import ValidationError


class TestSettingsDefaults:
    """Test default Settings values."""

    def test_default_session_lifetime(self):
        """Test default access token expiry is 2 hours."""
        from app.config import Settings

        s = Settings()
        assert s.access_token_expire_minutes == 120

    def test_cookie_max_age_derived_from_token_expiry(self):
        """Test jwt_cookie_max_age is derived from access_token_expire_minutes."""
        from app.config import Settings

        s = Settings()
        assert s.jwt_cookie_max_age == s.access_token_expire_minutes * 60
        assert s.jwt_cookie_max_age == 7200  # 2h in seconds


class TestSettingsEnvOverride:
    """Test environment variable overrides on fresh Settings instances."""

    def test_token_expiry_env_override(self, monkeypatch):
        """Test MYGARAGE_ACCESS_TOKEN_EXPIRE_MINUTES overrides default."""
        monkeypatch.setenv("MYGARAGE_ACCESS_TOKEN_EXPIRE_MINUTES", "30")

        from app.config import Settings

        s = Settings()
        assert s.access_token_expire_minutes == 30
        assert s.jwt_cookie_max_age == 1800  # 30 * 60

    def test_secret_key_env_override(self, monkeypatch):
        """Test MYGARAGE_SECRET_KEY overrides file-based generation."""
        monkeypatch.setenv("MYGARAGE_SECRET_KEY", "test-secret-from-env")

        from app.config import Settings

        s = Settings()
        assert s.secret_key == "test-secret-from-env"


class TestCSRFTokenExpiry:
    """Test CSRF token expiry derives from settings."""

    def test_csrf_expiry_uses_configured_lifetime(self):
        """Test CSRFToken.get_expiry_time() uses access_token_expire_minutes."""
        from datetime import timedelta

        from app.models.csrf_token import CSRFToken
        from app.utils.datetime_utils import utc_now

        now = utc_now()
        expiry = CSRFToken.get_expiry_time()

        # Should be approximately 2 hours from now (default)
        expected = now + timedelta(minutes=120)
        delta = abs((expiry - expected).total_seconds())
        assert delta < 5  # Within 5 seconds tolerance

    def test_csrf_expiry_accepts_custom_minutes(self):
        """Test CSRFToken.get_expiry_time(minutes=N) works."""
        from datetime import timedelta

        from app.models.csrf_token import CSRFToken
        from app.utils.datetime_utils import utc_now

        now = utc_now()
        expiry = CSRFToken.get_expiry_time(minutes=30)

        expected = now + timedelta(minutes=30)
        delta = abs((expiry - expected).total_seconds())
        assert delta < 5


class TestServiceLinkPort:
    """Regression tests for issue #102 — K8s/Docker service-link PORT collision."""

    def test_kubernetes_service_link_port_is_ignored(self, monkeypatch):
        """A K8s Service named 'mygarage' injects MYGARAGE_PORT=tcp://ip:port.

        That must not crash startup; the port falls back to the default.
        """
        monkeypatch.setenv("MYGARAGE_PORT", "tcp://10.104.104.172:8686")

        from app.config import Settings

        s = Settings()
        assert s.port == 8686  # default, not the tcp:// string

    def test_explicit_numeric_port_still_applies(self, monkeypatch):
        """A real integer MYGARAGE_PORT override is preserved."""
        monkeypatch.setenv("MYGARAGE_PORT", "9000")

        from app.config import Settings

        s = Settings()
        assert s.port == 9000

    def test_blank_port_falls_back_to_default(self, monkeypatch):
        """An empty MYGARAGE_PORT falls back to the default rather than erroring."""
        monkeypatch.setenv("MYGARAGE_PORT", "")

        from app.config import Settings

        s = Settings()
        assert s.port == 8686

    def test_default_port_when_unset(self):
        """Sanity: with no env var, the default port applies."""
        from app.config import Settings

        s = Settings()
        assert s.port == 8686


class TestCookieSameSite:
    """MYGARAGE_JWT_COOKIE_SAMESITE is checked at startup, not at the first login.

    Starlette asserts the value inside set_cookie, so a typo used to 500 the
    login route instead of stopping the app.
    """

    def test_any_case_works_and_default_is_lax(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Lax, STRICT and none all load lowercased; unset stays lax."""
        from app.config import Settings

        monkeypatch.delenv("MYGARAGE_JWT_COOKIE_SAMESITE", raising=False)
        assert Settings().jwt_cookie_samesite == "lax"

        for raw, expected in (("Lax", "lax"), ("STRICT", "strict"), ("none", "none")):
            monkeypatch.setenv("MYGARAGE_JWT_COOKIE_SAMESITE", raw)
            assert Settings().jwt_cookie_samesite == expected

    def test_a_typo_fails_at_startup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unknown value is a validation error naming the field."""
        from app.config import Settings

        monkeypatch.setenv("MYGARAGE_JWT_COOKIE_SAMESITE", "bogus")
        with pytest.raises(ValidationError, match="jwt_cookie_samesite"):
            Settings()

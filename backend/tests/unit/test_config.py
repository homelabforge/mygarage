"""Unit tests for Settings configuration and derivation."""


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

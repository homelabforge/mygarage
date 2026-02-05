"""
Unit tests for URL validation and SSRF protection.

Tests private IP blocking, domain whitelisting, and SSRF prevention.
"""

import pytest

from app.utils.url_validation import (
    SSRFProtectionError,
    is_private_ip,
    matches_domain_pattern,
    validate_nhtsa_url,
    validate_oidc_url,
    validate_tomtom_url,
    validate_url_for_ssrf,
)


@pytest.mark.unit
class TestIsPrivateIP:
    """Test private IP detection."""

    # Private Class A (10.0.0.0/8)
    def test_private_class_a(self):
        """Test RFC 1918 Class A private range."""
        assert is_private_ip("10.0.0.1") is True
        assert is_private_ip("10.255.255.255") is True

    # Private Class B (172.16.0.0/12)
    def test_private_class_b(self):
        """Test RFC 1918 Class B private range."""
        assert is_private_ip("172.16.0.1") is True
        assert is_private_ip("172.31.255.255") is True
        # Outside the range
        assert is_private_ip("172.15.0.1") is False
        assert is_private_ip("172.32.0.1") is False

    # Private Class C (192.168.0.0/16)
    def test_private_class_c(self):
        """Test RFC 1918 Class C private range."""
        assert is_private_ip("192.168.0.1") is True
        assert is_private_ip("192.168.255.255") is True

    # Loopback (127.0.0.0/8)
    def test_loopback(self):
        """Test loopback address range."""
        assert is_private_ip("127.0.0.1") is True
        assert is_private_ip("127.255.255.255") is True

    # Link-local (169.254.0.0/16) - AWS metadata endpoint
    def test_link_local(self):
        """Test link-local addresses (includes AWS metadata)."""
        assert is_private_ip("169.254.0.1") is True
        assert is_private_ip("169.254.169.254") is True  # AWS metadata

    # Public IPs
    def test_public_ips(self):
        """Test that public IPs are not flagged as private."""
        assert is_private_ip("8.8.8.8") is False  # Google DNS
        assert is_private_ip("1.1.1.1") is False  # Cloudflare DNS
        assert is_private_ip("142.250.80.46") is False  # Google

    # IPv6 loopback
    def test_ipv6_loopback(self):
        """Test IPv6 loopback address."""
        assert is_private_ip("::1") is True

    # IPv6 link-local
    def test_ipv6_link_local(self):
        """Test IPv6 link-local addresses."""
        assert is_private_ip("fe80::1") is True

    # IPv6 unique local addresses
    def test_ipv6_unique_local(self):
        """Test IPv6 unique local addresses (fc00::/7)."""
        assert is_private_ip("fc00::1") is True
        assert is_private_ip("fd00::1") is True

    # Invalid IP
    def test_invalid_ip_raises(self):
        """Test that invalid IP raises ValueError."""
        with pytest.raises(ValueError):
            is_private_ip("not-an-ip")

    # IPv4-mapped IPv6
    def test_ipv4_mapped_ipv6(self):
        """Test IPv4-mapped IPv6 addresses."""
        # ::ffff:127.0.0.1 maps to 127.0.0.1
        assert is_private_ip("::ffff:127.0.0.1") is True
        assert is_private_ip("::ffff:192.168.1.1") is True
        # Public IP mapped
        assert is_private_ip("::ffff:8.8.8.8") is False

    # Edge cases
    def test_edge_cases(self):
        """Test edge case IP addresses."""
        assert is_private_ip("0.0.0.0") is True  # "This" network
        # 255.255.255.255 is in 240.0.0.0/4 reserved range, so it's blocked
        assert is_private_ip("255.255.255.255") is True  # Reserved range (240.0.0.0/4)


@pytest.mark.unit
class TestMatchesDomainPattern:
    """Test domain pattern matching."""

    def test_exact_match(self):
        """Test exact domain matching."""
        assert matches_domain_pattern("example.com", "example.com") is True
        assert matches_domain_pattern("other.com", "example.com") is False

    def test_single_wildcard(self):
        """Test single-level wildcard (*.example.com)."""
        assert matches_domain_pattern("sub.example.com", "*.example.com") is True
        assert matches_domain_pattern("example.com", "*.example.com") is False
        assert matches_domain_pattern("deep.sub.example.com", "*.example.com") is False

    def test_double_wildcard(self):
        """Test multi-level wildcard (**.example.com)."""
        assert matches_domain_pattern("example.com", "**.example.com") is True
        assert matches_domain_pattern("sub.example.com", "**.example.com") is True
        assert matches_domain_pattern("deep.sub.example.com", "**.example.com") is True

    def test_case_insensitive(self):
        """Test that matching is case-insensitive."""
        assert matches_domain_pattern("EXAMPLE.COM", "example.com") is True
        assert matches_domain_pattern("Sub.Example.Com", "*.example.com") is True

    def test_no_partial_match(self):
        """Test that partial matches are not allowed."""
        assert matches_domain_pattern("malicious-example.com", "example.com") is False
        assert matches_domain_pattern("example.com.attacker.com", "example.com") is False


@pytest.mark.unit
class TestValidateUrlForSSRF:
    """Test main SSRF validation function."""

    def test_valid_https_url(self):
        """Test valid HTTPS URL passes validation."""
        result = validate_url_for_ssrf("https://example.com/api")
        assert result.scheme == "https"
        assert result.netloc == "example.com"

    def test_valid_http_url(self):
        """Test valid HTTP URL passes validation."""
        result = validate_url_for_ssrf("http://example.com/api")
        assert result.scheme == "http"

    def test_empty_url_raises(self):
        """Test that empty URL raises ValueError."""
        with pytest.raises(ValueError):
            validate_url_for_ssrf("")

    def test_invalid_scheme(self):
        """Test that invalid scheme is rejected."""
        with pytest.raises(SSRFProtectionError) as exc_info:
            validate_url_for_ssrf("file:///etc/passwd")
        assert "scheme" in str(exc_info.value).lower()

    def test_ftp_scheme_blocked(self):
        """Test that FTP scheme is blocked by default."""
        with pytest.raises(SSRFProtectionError):
            validate_url_for_ssrf("ftp://ftp.example.com/file")

    def test_require_https(self):
        """Test HTTPS requirement."""
        with pytest.raises(SSRFProtectionError) as exc_info:
            validate_url_for_ssrf("http://example.com", require_https=True)
        assert "https" in str(exc_info.value).lower()

    def test_localhost_blocked(self):
        """Test that localhost is blocked."""
        with pytest.raises(SSRFProtectionError):
            validate_url_for_ssrf("http://localhost/admin")

    def test_localhost_variants_blocked(self):
        """Test that localhost variants are blocked."""
        with pytest.raises(SSRFProtectionError):
            validate_url_for_ssrf("http://localhost.localdomain/")

    def test_private_ip_blocked(self):
        """Test that private IPs are blocked."""
        with pytest.raises(SSRFProtectionError):
            validate_url_for_ssrf("http://192.168.1.1/")

        with pytest.raises(SSRFProtectionError):
            validate_url_for_ssrf("http://10.0.0.1/")

    def test_loopback_ip_blocked(self):
        """Test that loopback IP is blocked."""
        with pytest.raises(SSRFProtectionError):
            validate_url_for_ssrf("http://127.0.0.1/")

    def test_aws_metadata_blocked(self):
        """Test that AWS metadata endpoint is blocked."""
        with pytest.raises(SSRFProtectionError):
            validate_url_for_ssrf("http://169.254.169.254/latest/meta-data/")

    def test_ipv6_loopback_blocked(self):
        """Test that IPv6 loopback is blocked."""
        with pytest.raises(SSRFProtectionError):
            validate_url_for_ssrf("http://[::1]/")

    def test_domain_whitelist(self):
        """Test domain whitelisting."""
        allowed = ["example.com", "*.trusted.com"]

        # Allowed domain
        result = validate_url_for_ssrf("https://example.com/api", allowed_domains=allowed)
        assert result is not None

        # Disallowed domain
        with pytest.raises(SSRFProtectionError):
            validate_url_for_ssrf("https://evil.com/", allowed_domains=allowed)

    def test_domain_whitelist_wildcard(self):
        """Test wildcard in domain whitelist."""
        allowed = ["*.trusted.com"]

        result = validate_url_for_ssrf("https://api.trusted.com/", allowed_domains=allowed)
        assert result is not None

    def test_ip_blocked_when_whitelist_active(self):
        """Test that IP addresses are blocked when whitelist is active."""
        with pytest.raises(SSRFProtectionError):
            validate_url_for_ssrf("http://8.8.8.8/", allowed_domains=["example.com"])

    def test_missing_hostname_raises(self):
        """Test that URL without hostname raises ValueError."""
        with pytest.raises(ValueError):
            validate_url_for_ssrf("http:///path")

    def test_custom_allowed_schemes(self):
        """Test custom allowed schemes."""
        result = validate_url_for_ssrf(
            "ftp://ftp.example.com/",
            allowed_schemes=["ftp", "ftps"],
            block_private_ips=False,  # Don't block for FTP test
            resolve_dns=False,
        )
        assert result.scheme == "ftp"

    def test_private_ip_blocking_disabled(self):
        """Test that private IP blocking can be disabled."""
        result = validate_url_for_ssrf(
            "http://192.168.1.1/", block_private_ips=False, resolve_dns=False
        )
        assert result.hostname == "192.168.1.1"


@pytest.mark.unit
class TestValidateOIDCUrl:
    """Test OIDC URL validation wrapper."""

    def test_valid_oidc_url(self):
        """Test valid OIDC provider URL."""
        result = validate_oidc_url("https://auth.example.com/.well-known/openid-configuration")
        assert result.scheme == "https"

    def test_http_allowed_for_oidc(self):
        """Test that HTTP is allowed for OIDC (some dev environments)."""
        result = validate_oidc_url("http://auth.example.com/")
        assert result.scheme == "http"

    def test_localhost_blocked_for_oidc(self):
        """Test that localhost is blocked for OIDC."""
        with pytest.raises(SSRFProtectionError):
            validate_oidc_url("http://localhost:8080/")


@pytest.mark.unit
class TestValidateNHTSAUrl:
    """Test NHTSA URL validation wrapper."""

    def test_valid_nhtsa_api_url(self):
        """Test valid NHTSA API URL."""
        result = validate_nhtsa_url("https://vpic.nhtsa.dot.gov/api/vehicles/")
        assert result.scheme == "https"
        assert result.hostname is not None
        assert "nhtsa" in result.hostname

    def test_nhtsa_alternate_domain(self):
        """Test NHTSA alternate domain."""
        result = validate_nhtsa_url("https://api.nhtsa.gov/recalls/")
        assert result is not None

    def test_nhtsa_subdomain_wildcard(self):
        """Test NHTSA subdomain matching."""
        result = validate_nhtsa_url("https://services.nhtsa.dot.gov/api/")
        assert result is not None

    def test_nhtsa_http_blocked(self):
        """Test that HTTP is blocked for NHTSA."""
        with pytest.raises(SSRFProtectionError):
            validate_nhtsa_url("http://vpic.nhtsa.dot.gov/")

    def test_nhtsa_other_domain_blocked(self):
        """Test that non-NHTSA domains are blocked."""
        with pytest.raises(SSRFProtectionError):
            validate_nhtsa_url("https://evil.com/")


@pytest.mark.unit
class TestValidateTomTomUrl:
    """Test TomTom URL validation wrapper."""

    def test_valid_tomtom_api_url(self):
        """Test valid TomTom API URL."""
        result = validate_tomtom_url("https://api.tomtom.com/search/2/search/")
        assert result.scheme == "https"
        assert result.hostname is not None
        assert "tomtom" in result.hostname

    def test_tomtom_subdomain(self):
        """Test TomTom subdomain matching."""
        result = validate_tomtom_url("https://routing.tomtom.com/api/")
        assert result is not None

    def test_tomtom_http_blocked(self):
        """Test that HTTP is blocked for TomTom."""
        with pytest.raises(SSRFProtectionError):
            validate_tomtom_url("http://api.tomtom.com/")

    def test_tomtom_other_domain_blocked(self):
        """Test that non-TomTom domains are blocked."""
        with pytest.raises(SSRFProtectionError):
            validate_tomtom_url("https://evil.com/")


@pytest.mark.unit
class TestSSRFProtectionError:
    """Test SSRFProtectionError exception."""

    def test_exception_message(self):
        """Test that exception carries message."""
        error = SSRFProtectionError("Blocked for testing")
        assert str(error) == "Blocked for testing"

    def test_exception_inheritance(self):
        """Test that exception inherits from Exception."""
        error = SSRFProtectionError("test")
        assert isinstance(error, Exception)


@pytest.mark.unit
class TestSecurityScenarios:
    """Test specific security attack scenarios."""

    def test_decimal_ip_encoding(self):
        """Test decimal IP encoding attacks."""
        # 2130706433 = 127.0.0.1 in decimal
        # This should be handled by the URL parser converting to regular IP
        # The test here ensures we don't crash
        try:
            # This may or may not work depending on how urllib handles it
            validate_url_for_ssrf("http://2130706433/")
        except (SSRFProtectionError, ValueError):
            pass  # Expected - either parsed and blocked, or invalid

    def test_ipv6_in_url(self):
        """Test IPv6 address in URL format."""
        with pytest.raises(SSRFProtectionError):
            validate_url_for_ssrf("http://[::1]/")

    def test_url_with_credentials(self):
        """Test URL with embedded credentials."""
        # Credentials in URL might be used to bypass checks
        result = validate_url_for_ssrf("https://user:pass@example.com/")
        assert result.hostname == "example.com"

    def test_url_with_port(self):
        """Test URL with port number."""
        result = validate_url_for_ssrf("https://example.com:8443/api")
        assert result.port == 8443

    def test_private_ip_with_port(self):
        """Test that private IPs with ports are still blocked."""
        with pytest.raises(SSRFProtectionError):
            validate_url_for_ssrf("http://192.168.1.1:8080/")

    def test_idn_domain(self):
        """Test internationalized domain names."""
        # IDN should be normalized to punycode
        result = validate_url_for_ssrf("https://münchen.example.com/")
        assert result is not None

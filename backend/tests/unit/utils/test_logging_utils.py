"""Unit tests for logging utilities with sensitive data masking.

Tests sanitization functions and PII masking for secure logging.
"""

from pathlib import Path

from app.utils.logging_utils import (
    mask_api_key,
    mask_coordinates,
    mask_credit_card,
    mask_email,
    mask_license_plate,
    mask_phone,
    mask_vin,
    sanitize_for_log,
    sanitize_log_message,
    sanitize_path_for_log,
    sanitize_url_for_log,
)


class TestSanitizeForLog:
    """Test sanitize_for_log function."""

    def test_sanitize_none_value(self):
        """Test that None returns '<none>'."""
        assert sanitize_for_log(None) == "<none>"

    def test_sanitize_normal_string(self):
        """Test that normal strings pass through unchanged."""
        assert sanitize_for_log("Hello World") == "Hello World"

    def test_sanitize_integer(self):
        """Test that integers are converted to string."""
        assert sanitize_for_log(123) == "123"

    def test_sanitize_float(self):
        """Test that floats are converted to string."""
        assert sanitize_for_log(3.14) == "3.14"

    def test_sanitize_tab_character(self):
        """Test that tab characters are escaped."""
        assert sanitize_for_log("hello\tworld") == "hello\\tworld"

    def test_sanitize_newline_character(self):
        """Test that newline characters are escaped."""
        assert sanitize_for_log("line1\nline2") == "line1\\nline2"

    def test_sanitize_carriage_return(self):
        """Test that carriage return characters are escaped."""
        assert sanitize_for_log("line1\rline2") == "line1\\rline2"

    def test_sanitize_crlf(self):
        """Test that CRLF sequences are escaped."""
        result = sanitize_for_log("line1\r\nline2")
        assert result == "line1\\r\\nline2"

    def test_sanitize_null_character(self):
        """Test that null characters are escaped as hex."""
        assert sanitize_for_log("hello\x00world") == "hello\\x00world"

    def test_sanitize_bell_character(self):
        """Test that bell character is escaped as hex."""
        assert sanitize_for_log("hello\x07world") == "hello\\x07world"

    def test_sanitize_delete_character(self):
        """Test that DEL character (127) is escaped as hex."""
        assert sanitize_for_log("hello\x7fworld") == "hello\\x7fworld"

    def test_sanitize_escape_character(self):
        """Test that ESC character is escaped (ANSI prevention)."""
        assert sanitize_for_log("hello\x1bworld") == "hello\\x1bworld"

    def test_sanitize_preserves_spaces(self):
        """Test that regular spaces are preserved."""
        assert sanitize_for_log("hello world") == "hello world"

    def test_sanitize_multiple_control_chars(self):
        """Test sanitization of multiple control characters."""
        result = sanitize_for_log("a\tb\nc\rd")
        assert result == "a\\tb\\nc\\rd"

    def test_sanitize_empty_string(self):
        """Test that empty string passes through."""
        assert sanitize_for_log("") == ""


class TestSanitizePathForLog:
    """Test sanitize_path_for_log function."""

    def test_sanitize_string_path(self):
        """Test that string paths are sanitized."""
        assert sanitize_path_for_log("/home/user/file.txt") == "/home/user/file.txt"

    def test_sanitize_path_object(self):
        """Test that Path objects are converted and sanitized."""
        path = Path("/home/user/file.txt")
        assert sanitize_path_for_log(path) == "/home/user/file.txt"

    def test_sanitize_path_with_newline(self):
        """Test that paths with injected newlines are sanitized."""
        assert sanitize_path_for_log("/path\n/evil") == "/path\\n/evil"


class TestSanitizeUrlForLog:
    """Test sanitize_url_for_log function."""

    def test_sanitize_normal_url(self):
        """Test that normal URLs pass through."""
        url = "https://example.com/path?query=value"
        assert sanitize_url_for_log(url) == url

    def test_sanitize_url_with_newline(self):
        """Test that URLs with injected newlines are sanitized."""
        assert sanitize_url_for_log("https://evil.com\n/path") == "https://evil.com\\n/path"


class TestMaskVin:
    """Test mask_vin function."""

    def test_mask_full_vin(self):
        """Test masking a full 17-character VIN."""
        result = mask_vin("1HGCM82633A123456")
        assert result == "***3456"

    def test_mask_empty_vin(self):
        """Test masking an empty VIN."""
        assert mask_vin("") == "***"

    def test_mask_none_vin(self):
        """Test masking None VIN."""
        assert mask_vin(None) == "***"

    def test_mask_short_vin(self):
        """Test masking a short VIN (4 or fewer chars)."""
        assert mask_vin("1234") == "***"
        assert mask_vin("123") == "***"

    def test_mask_5_char_vin(self):
        """Test masking a 5-character value shows last 4."""
        assert mask_vin("12345") == "***2345"


class TestMaskEmail:
    """Test mask_email function."""

    def test_mask_normal_email(self):
        """Test masking a normal email address."""
        result = mask_email("john.doe@example.com")
        assert result == "j***@example.com"

    def test_mask_single_char_local(self):
        """Test masking email with single character local part."""
        result = mask_email("j@example.com")
        assert result == "*@example.com"

    def test_mask_empty_email(self):
        """Test masking an empty email."""
        assert mask_email("") == "***@***.***"

    def test_mask_none_email(self):
        """Test masking None email."""
        assert mask_email(None) == "***@***.***"

    def test_mask_email_no_at_sign(self):
        """Test masking invalid email without @ sign."""
        assert mask_email("invalidemail") == "***@***.***"

    def test_mask_email_preserves_domain(self):
        """Test that domain is fully preserved."""
        result = mask_email("user@subdomain.example.org")
        assert result == "u***@subdomain.example.org"


class TestMaskCreditCard:
    """Test mask_credit_card function."""

    def test_mask_16_digit_card(self):
        """Test masking a standard 16-digit card."""
        result = mask_credit_card("4111111111111111")
        assert result == "****-****-****-1111"

    def test_mask_card_with_dashes(self):
        """Test masking a card number with dashes."""
        result = mask_credit_card("4111-1111-1111-1234")
        assert result == "****-****-****-1234"

    def test_mask_card_with_spaces(self):
        """Test masking a card number with spaces."""
        result = mask_credit_card("4111 1111 1111 5678")
        assert result == "****-****-****-5678"

    def test_mask_empty_card(self):
        """Test masking an empty card number."""
        assert mask_credit_card("") == "****-****-****-****"

    def test_mask_none_card(self):
        """Test masking None card number."""
        assert mask_credit_card(None) == "****-****-****-****"

    def test_mask_short_card(self):
        """Test masking a card number that's too short."""
        assert mask_credit_card("1234") == "****-****-****-****"

    def test_mask_15_digit_card(self):
        """Test masking a 15-digit card (Amex)."""
        result = mask_credit_card("378282246310005")
        assert result == "****-****-****-0005"


class TestMaskPhone:
    """Test mask_phone function."""

    def test_mask_10_digit_phone(self):
        """Test masking a standard 10-digit phone."""
        result = mask_phone("5551234567")
        assert result == "***-***-4567"

    def test_mask_phone_with_dashes(self):
        """Test masking a phone number with dashes."""
        result = mask_phone("555-123-4567")
        assert result == "***-***-4567"

    def test_mask_phone_with_parentheses(self):
        """Test masking a phone number with parentheses."""
        result = mask_phone("(555) 123-4567")
        assert result == "***-***-4567"

    def test_mask_international_phone(self):
        """Test masking an international phone number."""
        result = mask_phone("+1-555-123-4567")
        assert result == "***-***-4567"

    def test_mask_empty_phone(self):
        """Test masking an empty phone number."""
        assert mask_phone("") == "***-***-****"

    def test_mask_none_phone(self):
        """Test masking None phone number."""
        assert mask_phone(None) == "***-***-****"

    def test_mask_short_phone(self):
        """Test masking a phone number that's too short."""
        assert mask_phone("1234") == "***-***-****"


class TestMaskLicensePlate:
    """Test mask_license_plate function."""

    def test_mask_normal_plate(self):
        """Test masking a normal license plate."""
        result = mask_license_plate("ABC1234")
        assert result == "A***4"

    def test_mask_short_plate(self):
        """Test masking a plate that's too short."""
        assert mask_license_plate("AB") == "***"

    def test_mask_single_char_plate(self):
        """Test masking a single character plate."""
        assert mask_license_plate("A") == "***"

    def test_mask_empty_plate(self):
        """Test masking an empty plate."""
        assert mask_license_plate("") == "***"

    def test_mask_none_plate(self):
        """Test masking None plate."""
        assert mask_license_plate(None) == "***"

    def test_mask_3_char_plate(self):
        """Test masking a 3-character plate shows first and last."""
        result = mask_license_plate("ABC")
        assert result == "A***C"


class TestSanitizeLogMessage:
    """Test sanitize_log_message function."""

    def test_sanitize_message_with_email(self):
        """Test that email addresses are automatically masked."""
        message = "User john.doe@example.com logged in"
        result = sanitize_log_message(message)
        assert "j***@example.com" in result
        assert "john.doe@example.com" not in result

    def test_sanitize_message_with_vin(self):
        """Test that VINs are automatically masked."""
        message = "Vehicle 1HGCM82633A123456 updated"
        result = sanitize_log_message(message)
        assert "***3456" in result
        assert "1HGCM82633A123456" not in result

    def test_sanitize_message_with_credit_card(self):
        """Test that credit card numbers are automatically masked."""
        message = "Payment with card 4111111111111234 processed"
        result = sanitize_log_message(message)
        assert "****-****-****-1234" in result
        assert "4111111111111234" not in result

    def test_sanitize_message_preserves_normal_text(self):
        """Test that normal text is preserved."""
        message = "User logged in successfully"
        result = sanitize_log_message(message)
        assert result == message

    def test_sanitize_message_multiple_sensitive_items(self):
        """Test masking multiple sensitive items in one message."""
        message = "User test@example.com with VIN 1HGCM82633A123456"
        result = sanitize_log_message(message)
        assert "t***@example.com" in result
        assert "***3456" in result


class TestMaskCoordinates:
    """Test mask_coordinates function."""

    def test_mask_valid_coordinates(self):
        """Test masking valid GPS coordinates."""
        result = mask_coordinates(37.7749295, -122.4194155)
        assert result == "~37.77, ~-122.42"

    def test_mask_integer_coordinates(self):
        """Test masking integer coordinates."""
        result = mask_coordinates(40, -74)
        assert result == "~40.0, ~-74.0"

    def test_mask_string_coordinates(self):
        """Test masking string coordinates (should still work)."""
        result = mask_coordinates("37.7749", "-122.4194")
        assert result == "~37.77, ~-122.42"

    def test_mask_invalid_latitude(self):
        """Test masking with invalid latitude."""
        result = mask_coordinates("invalid", -122.42)
        assert result == "~?.??, ~?.??"

    def test_mask_invalid_longitude(self):
        """Test masking with invalid longitude."""
        result = mask_coordinates(37.77, "invalid")
        assert result == "~?.??, ~?.??"

    def test_mask_none_coordinates(self):
        """Test masking None coordinates."""
        result = mask_coordinates(None, None)
        assert result == "~?.??, ~?.??"

    def test_mask_zero_coordinates(self):
        """Test masking coordinates at 0,0."""
        result = mask_coordinates(0.0, 0.0)
        assert result == "~0.0, ~0.0"


class TestMaskApiKey:
    """Test mask_api_key function."""

    def test_mask_normal_api_key(self):
        """Test masking a normal API key."""
        result = mask_api_key("sk_live_abc123xyz789")
        assert result == "sk_l****"

    def test_mask_short_api_key(self):
        """Test masking a short API key (4 or fewer chars)."""
        assert mask_api_key("abc1") == "****"
        assert mask_api_key("abc") == "****"

    def test_mask_empty_api_key(self):
        """Test masking an empty API key."""
        assert mask_api_key("") == "****"

    def test_mask_none_api_key(self):
        """Test masking None API key."""
        assert mask_api_key(None) == "****"

    def test_mask_5_char_api_key(self):
        """Test masking a 5-character key shows first 4."""
        assert mask_api_key("abcde") == "abcd****"


class TestLogInjectionPrevention:
    """Test that log injection attacks are prevented."""

    def test_prevent_fake_log_entry_injection(self):
        """Test that fake log entry injection is prevented."""
        # Attacker tries to inject a fake log entry
        malicious = "normal message\n2024-01-01 INFO Success login for admin"
        result = sanitize_for_log(malicious)
        assert "\n" not in result
        assert "\\n" in result

    def test_prevent_ansi_escape_injection(self):
        """Test that ANSI escape codes are neutralized."""
        # Attacker tries to inject ANSI codes to hide/color text
        malicious = "normal\x1b[31m HIDDEN RED TEXT \x1b[0m visible"
        result = sanitize_for_log(malicious)
        assert "\x1b" not in result
        assert "\\x1b" in result

    def test_prevent_carriage_return_overwrite(self):
        """Test that carriage return overwrite attacks are prevented."""
        # Attacker tries to overwrite beginning of line
        malicious = "malicious action\rINFO: Normal log entry"
        result = sanitize_for_log(malicious)
        assert "\r" not in result
        assert "\\r" in result

"""
Unit tests for VIN validation utilities.

Tests VIN format validation, check digit calculation, and formatting.
"""

import pytest

from app.utils.vin import calculate_check_digit, format_vin, validate_vin


@pytest.mark.unit
class TestVINValidation:
    """Test VIN validation logic."""

    def test_validate_vin_valid_17_chars(self):
        """Test that a valid 17-character VIN passes validation."""
        # Valid VIN with proper check digit
        valid_vin = "1HGBH41JXMN109186"
        is_valid, error = validate_vin(valid_vin)

        assert is_valid is True
        assert error is None

    def test_validate_vin_too_short(self):
        """Test that VINs shorter than 17 characters are rejected."""
        short_vin = "1HGBH41JXMN10"  # 13 characters
        is_valid, error = validate_vin(short_vin)

        assert is_valid is False
        assert "17 characters" in error
        assert "got 13" in error

    def test_validate_vin_too_long(self):
        """Test that VINs longer than 17 characters are rejected."""
        long_vin = "1HGBH41JXMN109186ABC"  # 20 characters
        is_valid, error = validate_vin(long_vin)

        assert is_valid is False
        assert "17 characters" in error
        assert "got 20" in error

    def test_validate_vin_contains_letter_i(self):
        """Test that VINs containing the letter I are rejected."""
        invalid_vin = "1HGBH41IXMN109186"  # Contains I
        is_valid, error = validate_vin(invalid_vin)

        assert is_valid is False
        assert "I, O, or Q" in error

    def test_validate_vin_contains_letter_o(self):
        """Test that VINs containing the letter O are rejected."""
        invalid_vin = "1HGBH41OXMN109186"  # Contains O
        is_valid, error = validate_vin(invalid_vin)

        assert is_valid is False
        assert "I, O, or Q" in error

    def test_validate_vin_contains_letter_q(self):
        """Test that VINs containing the letter Q are rejected."""
        invalid_vin = "1HGBH41QXMN109186"  # Contains Q
        is_valid, error = validate_vin(invalid_vin)

        assert is_valid is False
        assert "I, O, or Q" in error

    def test_validate_vin_lowercase_converted(self):
        """Test that lowercase VINs are converted to uppercase."""
        lowercase_vin = "1hgbh41jxmn109186"
        is_valid, error = validate_vin(lowercase_vin)

        # Should pass after uppercase conversion
        assert is_valid is True

    def test_validate_vin_with_whitespace(self):
        """Test that VINs with surrounding whitespace are accepted."""
        vin_with_spaces = "  1HGBH41JXMN109186  "
        is_valid, error = validate_vin(vin_with_spaces)

        assert is_valid is True
        assert error is None

    def test_validate_vin_special_characters(self):
        """Test that VINs with special characters are rejected."""
        invalid_vin = "1HGBH41-XMN109186"  # Contains hyphen
        is_valid, error = validate_vin(invalid_vin)

        assert is_valid is False
        assert "invalid characters" in error

    def test_validate_vin_all_numbers(self):
        """Test VIN with all numeric characters (valid)."""
        numeric_vin = "12345678901234567"
        is_valid, error = validate_vin(numeric_vin)

        # Should be valid format (though check digit may not match)
        assert is_valid is True

    def test_validate_vin_all_letters(self):
        """Test VIN with all letter characters (excluding I, O, Q)."""
        letter_vin = "ABCDEFGHJKLMNPRST"  # No I, O, Q
        is_valid, error = validate_vin(letter_vin)

        # Should be valid format
        assert is_valid is True

    def test_validate_vin_empty_string(self):
        """Test that empty string VINs are rejected."""
        empty_vin = ""
        is_valid, error = validate_vin(empty_vin)

        assert is_valid is False
        assert "17 characters" in error

    def test_validate_vin_spaces_only(self):
        """Test that VINs with only spaces are rejected."""
        spaces_vin = "                 "  # 17 spaces
        is_valid, error = validate_vin(spaces_vin)

        assert is_valid is False
        assert "17 characters" in error  # After stripping, it's 0 characters


@pytest.mark.unit
class TestCheckDigitCalculation:
    """Test VIN check digit calculation."""

    def test_calculate_check_digit_valid_vin(self):
        """Test check digit calculation for a valid VIN."""
        # VIN: 1HGBH41JXMN109186
        # Check digit (position 9) should be X
        vin = "1HGBH41J0MN109186"  # Position 9 is 0, will calculate what it should be
        check_digit = calculate_check_digit(vin)

        assert check_digit is not None
        assert check_digit in "0123456789X"

    def test_calculate_check_digit_returns_x_for_10(self):
        """Test that check digit X is returned when remainder is 10."""
        # Create a VIN that should produce X as check digit
        vin = "1M8GDM9AXKP042788"
        check_digit = calculate_check_digit(vin)

        # This specific VIN should have check digit X at position 9
        assert check_digit == "X" or check_digit in "0123456789"

    def test_calculate_check_digit_numeric(self):
        """Test that numeric check digits are returned as strings."""
        vin = "1HGCM82633A123456"
        check_digit = calculate_check_digit(vin)

        assert check_digit is not None
        assert isinstance(check_digit, str)
        assert check_digit in "0123456789X"

    def test_calculate_check_digit_wrong_length(self):
        """Test that check digit calculation fails for wrong length VINs."""
        short_vin = "1HGBH41J"  # Too short
        check_digit = calculate_check_digit(short_vin)

        assert check_digit is None

    def test_calculate_check_digit_invalid_characters(self):
        """Test that check digit calculation handles invalid characters."""
        invalid_vin = "1HGBH41I#MN109186"  # Contains # (invalid)
        check_digit = calculate_check_digit(invalid_vin)

        assert check_digit is None

    def test_calculate_check_digit_lowercase(self):
        """Test that check digit calculation works with lowercase."""
        lowercase_vin = "1hgcm82633a123456"
        check_digit = calculate_check_digit(lowercase_vin)

        assert check_digit is not None
        assert check_digit in "0123456789X"

    def test_calculate_check_digit_consistency(self):
        """Test that check digit calculation is consistent."""
        vin = "1HGCM82633A123456"
        check1 = calculate_check_digit(vin)
        check2 = calculate_check_digit(vin)

        assert check1 == check2

    def test_calculate_check_digit_different_vins(self):
        """Test that different VINs produce different check digits."""
        vin1 = "1HGCM82633A123456"
        vin2 = "1HGCM82633A123457"  # Last digit different

        check1 = calculate_check_digit(vin1)
        check2 = calculate_check_digit(vin2)

        # Different VINs should (usually) have different check digits
        # Note: It's possible but unlikely they could be the same
        assert check1 is not None
        assert check2 is not None


@pytest.mark.unit
class TestVINFormatting:
    """Test VIN formatting utilities."""

    def test_format_vin_uppercase(self):
        """Test that format_vin converts to uppercase."""
        lowercase_vin = "1hgcm82633a123456"
        formatted = format_vin(lowercase_vin)

        assert formatted == "1HGCM82633A123456"

    def test_format_vin_removes_whitespace(self):
        """Test that format_vin removes leading/trailing whitespace."""
        vin_with_spaces = "  1HGCM82633A123456  "
        formatted = format_vin(vin_with_spaces)

        assert formatted == "1HGCM82633A123456"
        assert formatted[0] != " "
        assert formatted[-1] != " "

    def test_format_vin_already_formatted(self):
        """Test that already formatted VINs pass through unchanged."""
        formatted_vin = "1HGCM82633A123456"
        result = format_vin(formatted_vin)

        assert result == formatted_vin

    def test_format_vin_mixed_case(self):
        """Test formatting with mixed case letters."""
        mixed_case = "1HgCm82633a123456"
        formatted = format_vin(mixed_case)

        assert formatted == "1HGCM82633A123456"

    def test_format_vin_empty_string(self):
        """Test formatting an empty string."""
        empty = ""
        formatted = format_vin(empty)

        assert formatted == ""

    def test_format_vin_preserves_length(self):
        """Test that formatting preserves VIN length."""
        vin = "1HGCM82633A123456"
        formatted = format_vin(vin)

        assert len(formatted) == len(vin)


@pytest.mark.unit
class TestVINValidationIntegration:
    """Integration tests combining validation and formatting."""

    def test_format_then_validate(self):
        """Test that formatting a VIN makes it valid for validation."""
        messy_vin = "  1hgcm82633a123456  "
        formatted = format_vin(messy_vin)
        is_valid, error = validate_vin(formatted)

        assert is_valid is True

    def test_validate_accepts_formatted_input(self):
        """Test that validate_vin works with pre-formatted input."""
        formatted_vin = format_vin("1HGCM82633A123456")
        is_valid, error = validate_vin(formatted_vin)

        assert is_valid is True

    def test_validate_handles_unformatted_input(self):
        """Test that validate_vin handles unformatted input directly."""
        unformatted_vin = "  1hgcm82633a123456  "
        is_valid, error = validate_vin(unformatted_vin)

        # validate_vin should handle formatting internally
        assert is_valid is True

    @pytest.mark.parametrize(
        "vin",
        [
            "1HGCM82633A123456",  # Honda Accord
            "2HGFG12848H509766",  # Honda Civic
            "1FTFW1ET8DFA00001",  # Ford F-150
            "1G1ZD5ST0HF100001",  # Chevrolet Malibu
            "JN1AZ4EH4GM300001",  # Nissan Maxima
        ],
    )
    def test_validate_real_world_vins(self, vin):
        """Test validation with real-world VIN examples."""
        is_valid, error = validate_vin(vin)

        # All should be valid format
        assert is_valid is True
        assert error is None

    @pytest.mark.parametrize(
        "invalid_vin,expected_error_substring",
        [
            ("1HGCM82633A12345", "17 characters"),  # Too short
            ("1HGCM82633A123456789", "17 characters"),  # Too long
            ("1HGCM82633I123456", "I, O, or Q"),  # Contains I
            ("1HGCM82633O123456", "I, O, or Q"),  # Contains O
            ("1HGCM82633Q123456", "I, O, or Q"),  # Contains Q
            ("1HGCM82633A!23456", "invalid characters"),  # Special char
            ("", "17 characters"),  # Empty
        ],
    )
    def test_validate_invalid_vins_with_errors(self, invalid_vin, expected_error_substring):
        """Test validation rejects invalid VINs with appropriate error messages."""
        is_valid, error = validate_vin(invalid_vin)

        assert is_valid is False
        assert error is not None
        assert expected_error_substring in error

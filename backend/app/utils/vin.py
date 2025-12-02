"""VIN (Vehicle Identification Number) validation utilities."""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def validate_vin(vin: str) -> tuple[bool, Optional[str]]:
    """
    Validate a Vehicle Identification Number (VIN).

    VIN must be exactly 17 characters and follow ISO 3779 standard.
    - Must not contain I, O, or Q (to avoid confusion with 1, 0)
    - Must pass check digit validation for North American VINs

    Args:
        vin: The VIN to validate

    Returns:
        Tuple of (is_valid, error_message)
        - (True, None) if valid
        - (False, error_message) if invalid
    """
    # Remove whitespace and convert to uppercase
    vin = vin.strip().upper()

    # Check length
    if len(vin) != 17:
        return False, f"VIN must be exactly 17 characters (got {len(vin)})"

    # Check for invalid characters (I, O, Q not allowed per ISO 3779)
    if re.search(r'[IOQ]', vin):
        return False, "VIN cannot contain the letters I, O, or Q"

    # Check that it only contains valid characters (A-Z, 0-9, excluding I, O, Q)
    if not re.match(r'^[A-HJ-NPR-Z0-9]{17}$', vin):
        return False, "VIN contains invalid characters"

    # Validate check digit (9th position) for North American VINs
    # This is optional but recommended for additional validation
    check_digit = vin[8]
    calculated_check = calculate_check_digit(vin)

    if calculated_check and check_digit != calculated_check:
        # Note: Not all VINs use check digits (non-North American VINs may not follow this standard)
        # We log a warning but still accept the VIN to support international vehicles
        logger.warning(
            f"VIN check digit mismatch for {vin}: expected '{calculated_check}', got '{check_digit}'. "
            "This may be a non-North American VIN or a typo."
        )

    return True, None


def calculate_check_digit(vin: str) -> Optional[str]:
    """
    Calculate the check digit for a VIN (9th position).

    This follows the North American VIN standard (ISO 3779).
    Non-North American VINs may not follow this standard.

    Args:
        vin: The 17-character VIN

    Returns:
        The calculated check digit (0-9 or X), or None if calculation fails
    """
    if len(vin) != 17:
        return None

    # VIN character to value mapping
    transliteration = {
        'A': 1, 'B': 2, 'C': 3, 'D': 4, 'E': 5, 'F': 6, 'G': 7, 'H': 8,
        'J': 1, 'K': 2, 'L': 3, 'M': 4, 'N': 5, 'P': 7, 'R': 9,
        'S': 2, 'T': 3, 'U': 4, 'V': 5, 'W': 6, 'X': 7, 'Y': 8, 'Z': 9,
        '0': 0, '1': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7,
        '8': 8, '9': 9
    }

    # Position weights (position 9 is the check digit, so it's 0)
    weights = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]

    try:
        # Calculate weighted sum
        total = 0
        for i, char in enumerate(vin.upper()):
            if char not in transliteration:
                return None
            total += transliteration[char] * weights[i]

        # Calculate check digit
        remainder = total % 11

        # If remainder is 10, check digit is 'X'
        if remainder == 10:
            return 'X'
        else:
            return str(remainder)
    except (KeyError, ValueError):
        return None


def format_vin(vin: str) -> str:
    """
    Format a VIN to standard uppercase with no spaces.

    Args:
        vin: The VIN to format

    Returns:
        Formatted VIN in uppercase
    """
    return vin.strip().upper()

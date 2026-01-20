"""Logging utilities with sensitive data masking and log injection prevention."""

import re
from typing import Any


def sanitize_for_log(value: Any) -> str:
    """Sanitize a value for safe logging by removing control characters.

    This prevents log injection attacks where attackers could inject newlines,
    ANSI escape codes, or other control characters to forge log entries or
    manipulate log parsing systems.

    Args:
        value: Any value to sanitize for logging

    Returns:
        A string safe for logging with control characters removed/escaped
    """
    if value is None:
        return "<none>"

    # Convert to string
    text = str(value)

    # Remove or escape control characters (ASCII 0-31 and 127)
    # Keep common whitespace like space (32) but escape tabs, newlines, etc.
    sanitized = []
    for char in text:
        code = ord(char)
        if code == 9:  # Tab
            sanitized.append("\\t")
        elif code == 10:  # Newline
            sanitized.append("\\n")
        elif code == 13:  # Carriage return
            sanitized.append("\\r")
        elif code < 32 or code == 127:
            # Other control characters - show as hex escape
            sanitized.append(f"\\x{code:02x}")
        elif code == 27:  # ESC - ANSI escape sequences
            sanitized.append("\\x1b")
        else:
            sanitized.append(char)

    return "".join(sanitized)


def sanitize_path_for_log(path: Any) -> str:
    """Sanitize a file path for safe logging.

    Args:
        path: A path value (str or Path object)

    Returns:
        A sanitized string representation of the path
    """
    return sanitize_for_log(path)


def sanitize_url_for_log(url: Any) -> str:
    """Sanitize a URL for safe logging.

    Args:
        url: A URL string

    Returns:
        A sanitized string representation of the URL
    """
    return sanitize_for_log(url)


def mask_vin(vin: str) -> str:
    """Mask VIN number to show only last 4 digits.

    Args:
        vin: The VIN number to mask

    Returns:
        Masked VIN string (e.g., "***1234")
    """
    if not vin:
        return "***"
    if len(vin) <= 4:
        return "***"
    return f"***{vin[-4:]}"


def mask_email(email: str) -> str:
    """Mask email address to show only first char and domain.

    Args:
        email: The email address to mask

    Returns:
        Masked email string (e.g., "j***@example.com")
    """
    if not email or "@" not in email:
        return "***@***.***"

    local, domain = email.split("@", 1)
    if len(local) <= 1:
        masked_local = "*"
    else:
        masked_local = f"{local[0]}***"

    return f"{masked_local}@{domain}"


def mask_credit_card(card_number: str) -> str:
    """Mask credit card number to show only last 4 digits.

    Args:
        card_number: The credit card number to mask

    Returns:
        Masked card number (e.g., "****-****-****-1234")
    """
    if not card_number:
        return "****-****-****-****"

    # Remove any non-digit characters
    digits = re.sub(r"\D", "", card_number)

    if len(digits) <= 4:
        return "****-****-****-****"

    return f"****-****-****-{digits[-4:]}"


def mask_phone(phone: str) -> str:
    """Mask phone number to show only last 4 digits.

    Args:
        phone: The phone number to mask

    Returns:
        Masked phone number (e.g., "***-***-1234")
    """
    if not phone:
        return "***-***-****"

    # Remove any non-digit characters
    digits = re.sub(r"\D", "", phone)

    if len(digits) <= 4:
        return "***-***-****"

    return f"***-***-{digits[-4:]}"


def mask_license_plate(plate: str) -> str:
    """Mask license plate to show only first and last character.

    Args:
        plate: The license plate to mask

    Returns:
        Masked plate (e.g., "A***3")
    """
    if not plate:
        return "***"
    if len(plate) <= 2:
        return "***"

    return f"{plate[0]}***{plate[-1]}"


def sanitize_log_message(message: str) -> str:
    """Sanitize a log message by masking potential sensitive data.

    This function looks for patterns that might be VINs, emails, etc.
    and masks them automatically.

    Args:
        message: The log message to sanitize

    Returns:
        Sanitized log message
    """
    # Mask email addresses
    message = re.sub(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        lambda m: mask_email(m.group(0)),
        message,
    )

    # Mask potential credit card numbers (sequences of 13-19 digits)
    message = re.sub(r"\b\d{13,19}\b", lambda m: mask_credit_card(m.group(0)), message)

    # Mask potential VINs (17 character alphanumeric)
    message = re.sub(
        r"\b[A-HJ-NPR-Z0-9]{17}\b", lambda m: mask_vin(m.group(0)), message
    )

    return message


def mask_coordinates(latitude: float, longitude: float) -> str:
    """Mask GPS coordinates to reduce precision for privacy.

    Rounds to 2 decimal places (~1.1km precision) which is enough
    for debugging without revealing exact location.

    Args:
        latitude: The latitude coordinate
        longitude: The longitude coordinate

    Returns:
        Masked coordinate string (e.g., "~37.77, ~-122.42")
    """
    try:
        lat_masked = round(float(latitude), 2)
        lon_masked = round(float(longitude), 2)
        return f"~{lat_masked}, ~{lon_masked}"
    except (TypeError, ValueError):
        return "~?.??, ~?.??"


def mask_api_key(key: str) -> str:
    """Mask API key to show only first 4 characters.

    Args:
        key: The API key to mask

    Returns:
        Masked key string (e.g., "abc1****")
    """
    if not key:
        return "****"
    if len(key) <= 4:
        return "****"
    return f"{key[:4]}****"

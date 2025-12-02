"""Logging utilities with sensitive data masking."""

import re


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
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        lambda m: mask_email(m.group(0)),
        message
    )

    # Mask potential credit card numbers (sequences of 13-19 digits)
    message = re.sub(
        r'\b\d{13,19}\b',
        lambda m: mask_credit_card(m.group(0)),
        message
    )

    # Mask potential VINs (17 character alphanumeric)
    message = re.sub(
        r'\b[A-HJ-NPR-Z0-9]{17}\b',
        lambda m: mask_vin(m.group(0)),
        message
    )

    return message

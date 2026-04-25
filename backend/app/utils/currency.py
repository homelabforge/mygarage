"""Backend currency-symbol resolution for PDF/report rendering.

Used by PDF generators (ReportLab) that need a display symbol for a currency
code without shipping a dependency on Babel or the process-global `locale`
module. Covers the currencies the frontend exposes via SUPPORTED_CURRENCIES,
plus a safe fallback to the code itself for anything unknown.

This is NOT a full locale-aware currency formatter. It returns the symbol
only. Callers compose `f"{symbol}{value:,.2f}"` or equivalent.
"""

from __future__ import annotations

import re

from app.constants.i18n import SUPPORTED_CURRENCIES

# Canonical symbol per ISO 4217 code. Covers SUPPORTED_CURRENCIES from i18n.py
# plus a handful of common extras so future additions to the allowlist don't
# have to ship with a separate symbol update.
_CURRENCY_SYMBOLS: dict[str, str] = {
    "USD": "$",
    "CAD": "CA$",
    "AUD": "A$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "CNY": "¥",
    "INR": "₹",
    "KRW": "₩",
    "RUB": "₽",
    "UAH": "₴",
    "PLN": "zł",
    "CHF": "CHF",
    "SEK": "kr",
    "NOK": "kr",
    "DKK": "kr",
    "CZK": "Kč",
    "HUF": "Ft",
    "BRL": "R$",
    "MXN": "MX$",
    "ZAR": "R",
    "NZD": "NZ$",
    "SGD": "S$",
    "HKD": "HK$",
    "TRY": "₺",
    "ILS": "₪",
    "AED": "د.إ",
    "THB": "฿",
    "TWD": "NT$",
}


# Defence-in-depth: strict patterns used to reject malformed input before it
# hits a template. PDF endpoints pass these through unvalidated from the URL,
# so we treat them as untrusted.
_CURRENCY_CODE_RE = re.compile(r"^[A-Z]{3}$")
_LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


def is_valid_currency_code(code: str | None) -> bool:
    """Reject anything that isn't ISO 4217 shape (3 uppercase letters)."""
    return bool(code) and bool(_CURRENCY_CODE_RE.fullmatch(code or ""))


def is_valid_locale(locale: str | None) -> bool:
    """Reject anything that isn't BCP 47 shape."""
    return bool(locale) and bool(_LOCALE_RE.fullmatch(locale or ""))


def get_currency_symbol(currency_code: str | None, locale: str | None = "en-US") -> str:
    """Return a display symbol for the currency code.

    Falls back to the code itself for:
      - Malformed input (not matching `^[A-Z]{3}$`)
      - Codes outside SUPPORTED_CURRENCIES when the `locale` allowlist rejects them
      - Any code we don't have a symbol for in the map above

    Locale is accepted for future extension (e.g. switching CA$ vs $ depending
    on the user's locale) but the current implementation is locale-agnostic.
    """
    if not is_valid_currency_code(currency_code):
        # Malformed input: return USD symbol for empty input (pre-hotfix default)
        # and otherwise echo the uppercased code so the user can see the mistake.
        if not currency_code:
            return "$"
        return (currency_code or "").upper()

    code = (currency_code or "").upper()

    # Safety: if the code isn't in our allowlist AND isn't in our symbol map,
    # fall back to the code itself. Never return an unrecognised-source symbol.
    if code not in SUPPORTED_CURRENCIES and code not in _CURRENCY_SYMBOLS:
        return code

    return _CURRENCY_SYMBOLS.get(code, code)


def normalize_pdf_currency_params(currency_code: str | None, locale: str | None) -> tuple[str, str]:
    """Validate and default the (currency_code, locale) pair from a PDF request.

    Returns a tuple of safe values suitable for passing directly into
    get_currency_symbol() and ReportLab templates. Unknown/invalid input
    falls back to ("USD", "en-US") — matching the pre-hotfix behaviour so
    stale clients keep working.
    """
    code = (currency_code or "").upper() if is_valid_currency_code(currency_code) else "USD"

    # Locale only needs BCP-47 shape validation; the current PDF stack uses
    # the code-derived symbol regardless of locale. Restricting to
    # SUPPORTED_LANGUAGES would reject valid BCP-47 locales like de-DE or
    # fr-FR that users might reasonably send.
    safe_locale = locale if is_valid_locale(locale) else "en-US"

    return code, safe_locale

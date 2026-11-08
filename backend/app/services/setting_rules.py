"""Which settings the API may write, which values a reader can use, and how a switch is stored.

Two writers share these rules: the three generic write routes in
`app.routes.settings` (`POST /settings`, `PUT /settings/{key}`,
`POST /settings/batch`) and `BackupService.restore_settings_backup`. Each rule
does one of three things:

- `GENERIC_WRITABLE_KEYS` says which keys may be written. Only the routes apply
  it: the restore round-trips the instance's own export, which legitimately
  holds keys the API refuses (the `livelink_*` rows, provider usage counters,
  the Telegram offset).
- `check_setting_value` refuses a value its reader could not use. Both writers
  apply it.
- `canonical_setting_value` stores a switch written as any on/off word as
  "true" or "false" (D5a), so a reader that matches the exact word and one that
  reads leniently agree. Both writers apply it; it never refuses anything.

The key rule closes G3b-20, where an admin call could write any key, and with it
O-T1: a `livelink_telemetry_retention_days` of 0 written through the generic API
made the daily prune delete every raw reading and location point.
"""

from __future__ import annotations

import math

from app.constants.countries import (
    DEFAULT_COUNTRY_SETTING_KEY,
    is_country_code,
    normalize_country_code,
)
from app.schemas.livelink import TELEMETRY_RETENTION_MAX_DAYS, TELEMETRY_RETENTION_MIN_DAYS
from app.services.fuel_prices.france import API_URL_SETTING as FUEL_PRICES_API_URL_SETTING
from app.services.llm_client import (
    LLM_BASE_URL_SETTING,
    LLM_PRESET_SETTING,
    LLM_PROVIDER_PRESETS,
    is_http_url,
)
from app.services.recalls.rappelconso import API_URL_SETTING as RAPPELCONSO_API_URL_SETTING
from app.services.setting_switches import SWITCH_SETTING_KEYS
from app.services.settings_init import DEFAULT_SETTINGS
from app.services.settings_service import SWITCH_OFF_VALUES, SWITCH_ON_VALUES
from app.utils.household_time import TIMEZONE_SETTING_KEY
from app.utils.url_validation import validate_data_economie_url

#: Kept by the app itself, never by an admin: the running version, the last
#: recall checks (NHTSA, and RappelConso for #211), and how far the Telegram
#: poller has read.
SYSTEM_MAINTAINED_KEYS: frozenset[str] = frozenset(
    {"app_version", "nhtsa_last_check", "rappelconso_last_check", "telegram_update_offset"}
)

#: The LiveLink settings have their own typed routes (`routes/livelink_admin.py`),
#: which check every value; the generic API is a way round those checks.
TYPED_API_PREFIX = "livelink_"

#: Every seeded setting an admin may change, plus the household time zone, which
#: the System tab writes but nothing seeds. Derived from the seed list, so a newly
#: seeded setting is writable without a second edit here.
GENERIC_WRITABLE_KEYS: frozenset[str] = frozenset(
    key
    for key in DEFAULT_SETTINGS
    if key not in SYSTEM_MAINTAINED_KEYS and not key.startswith(TYPED_API_PREFIX)
) | {TIMEZONE_SETTING_KEY}

_AUTH_MODES = frozenset({"none", "local", "oidc"})


def canonical_setting_value(key: str, value: str | None) -> str | None:
    """`value` as it should be stored under `key`: a switch word becomes "true" or "false".

    Some readers (the settings screens among them) match the stored text
    exactly, so a switch written as "Yes" or "1" would read as off there and on
    through `parse_bool`. Storing the canonical word makes them agree. Nothing
    is refused.

    Args:
        key: The settings key being written.
        value: The value as submitted or as found in a backup file.

    Returns:
        For a key in `SWITCH_SETTING_KEYS`: "true" for a word in
        `SWITCH_ON_VALUES` and "false" for one in `SWITCH_OFF_VALUES`, in any
        case and with surrounding whitespace. Anything else, and every value
        under any other key, unchanged, blank and None included.
    """
    if key not in SWITCH_SETTING_KEYS or value is None:
        return value
    word = value.strip().lower()
    if word in SWITCH_ON_VALUES:
        return "true"
    if word in SWITCH_OFF_VALUES:
        return "false"
    return value


def _as_int(value: str) -> int:
    """`value` as an integer, or a ValueError a caller can show."""
    try:
        return int(value)
    except ValueError:
        raise ValueError("must be a whole number") from None


def check_setting_value(key: str, value: object) -> None:
    """Refuse a value whose reader would crash or do damage with it.

    Only those readers. The Notifications, Files and Integrations tabs re-send
    every stored value on each save, all or nothing, so a rule on a key whose
    reader already copes would only turn a harmless stored oddity into a tab
    that cannot save. Not checked for that reason: `notification_retry_attempts`
    and `email_smtp_port` (read through `_get_setting_int`, which falls back),
    `auto_archive_inactive_days`, `notify_def_low_threshold_percent` and
    `nhtsa_recall_check_interval` (their readers fall back), and the
    switches (`SettingsService.get_bool` reads leniently).

    `None` and `""` are blank. Anything else is read as `str(value)`, so a
    backup file's JSON number reaches the same rule as the string a form sends.

    Args:
        key: The settings key being written.
        value: The value as submitted or as found in a backup file.

    Raises:
        ValueError: The value would not survive its reader; the message says why.
    """
    text = "" if value is None else str(value)

    if key == "oidc_link_token_expire_minutes":
        # `create_pending_link` does a bare int() on it, and `get_oidc_config`
        # turns a stored null into "": a blank 500s every username link.
        if not text:
            raise ValueError("must be a whole number of minutes, at least 1")
        if _as_int(text) < 1:
            raise ValueError("must be at least 1")
    elif key == "oidc_link_max_password_attempts":
        # A blank reads as 3; a 0 refuses every link (`attempt_count >= 0`).
        if text and _as_int(text) < 1:
            raise ValueError("must be at least 1")
    elif key in ("notify_insurance_days", "notify_warranty_days"):
        # `check_expiring_documents` does a bare int(); a blank reads as 30.
        if text:
            _as_int(text)
    elif key == "notification_retry_delay":
        # A bare float() on every send; "inf" would sleep forever.
        if text:
            try:
                delay = float(text)
            except ValueError:
                raise ValueError("must be a number of seconds") from None
            if not math.isfinite(delay):
                raise ValueError("must be a finite number of seconds")
    elif key == "auth_mode":
        # Read lowercased, and anything but "none" demands a login, so a typo
        # locks the instance into a mode nobody set up. A blank reads as "local".
        if text and text.lower() not in _AUTH_MODES:
            raise ValueError("must be one of: none, local, oidc")
    elif key == "livelink_telemetry_retention_days":
        # The daily prune deletes everything older than now minus this many days.
        days = _as_int(text) if text else None
        if days is None or not TELEMETRY_RETENTION_MIN_DAYS <= days <= TELEMETRY_RETENTION_MAX_DAYS:
            raise ValueError(
                f"must be a whole number of days from {TELEMETRY_RETENTION_MIN_DAYS} "
                f"to {TELEMETRY_RETENTION_MAX_DAYS}"
            )
    elif key == DEFAULT_COUNTRY_SETTING_KEY:
        # Blank clears it; anything else must be a code the profile loader
        # and the frontend's Intl.DisplayNames both know (#211).
        if text and not is_country_code(normalize_country_code(text)):
            raise ValueError("must be an ISO 3166-1 alpha-2 country code")
    elif key == LLM_BASE_URL_SETTING:
        # The LLM client POSTs to it verbatim; a bare host or a typo would fail
        # every receipt parse and document read with an opaque 502 (#211).
        if text and not is_http_url(text):
            raise ValueError("must be an http(s) URL")
    elif key == LLM_PRESET_SETTING:
        # A hint for the settings card, from a fixed vocabulary (#211).
        if text and text not in LLM_PROVIDER_PRESETS:
            raise ValueError(f"must be one of: {', '.join(LLM_PROVIDER_PRESETS)}")
    elif key in (RAPPELCONSO_API_URL_SETTING, FUEL_PRICES_API_URL_SETTING):
        # The provider would fall back to the default and log an error on
        # every check; say so at the write instead (#211).
        if text:
            try:
                validate_data_economie_url(text)
            except Exception:  # noqa: BLE001 - SSRF or malformed, same answer
                raise ValueError("must be an https URL on data.economie.gouv.fr") from None

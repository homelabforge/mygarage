"""Which settings the generic settings API may write, and which values a reader can use.

Two writers share these rules: the three generic write routes in
`app.routes.settings` (`POST /settings`, `PUT /settings/{key}`,
`POST /settings/batch`) and `BackupService.restore_settings_backup`. The routes
apply both halves. The restore applies only `check_setting_value`: it
round-trips the instance's own export, which legitimately holds keys the API
refuses (the `livelink_*` rows, provider usage counters, the Telegram offset).

The key half closes G3b-20, where an admin call could write any key, and with it
O-T1: a `livelink_telemetry_retention_days` of 0 written through the generic API
made the daily prune delete every raw reading and location point.
"""

from __future__ import annotations

import math

from app.schemas.livelink import TELEMETRY_RETENTION_MAX_DAYS, TELEMETRY_RETENTION_MIN_DAYS
from app.services.settings_init import DEFAULT_SETTINGS
from app.utils.household_time import TIMEZONE_SETTING_KEY

#: Kept by the app itself, never by an admin: the running version, the last
#: recall check, and how far the Telegram poller has read.
SYSTEM_MAINTAINED_KEYS: frozenset[str] = frozenset(
    {"app_version", "nhtsa_last_check", "telegram_update_offset"}
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
    that cannot save. Not checked for that reason: `max_upload_size_mb` (uploads
    read the environment setting), `nhtsa_recall_check_interval` and
    `notify_service_days` / `notify_service_miles` (no backend reader),
    `notification_retry_attempts` and `email_smtp_port` (read through
    `_get_setting_int`, which falls back), `auto_archive_inactive_days` and
    `notify_def_low_threshold_percent` (their readers fall back), and the
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

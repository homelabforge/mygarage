"""The settings write rules: which keys the generic API writes, and which values a reader can use.

`app.services.setting_rules` is shared by the three generic write routes and the
settings restore. The route-level behaviour is pinned in
`tests/integration/routes/test_settings.py::TestGenericWriteAllowlist`; this
module pins the rule set itself.
"""

from __future__ import annotations

import pytest

from app.models.settings import Setting
from app.services.setting_rules import GENERIC_WRITABLE_KEYS, check_setting_value
from app.services.settings_init import DEFAULT_SETTINGS

# Every key a settings screen or E2E spec sends through `/settings/batch` today,
# grouped by the file that sends it. If one of these stops being writable, that
# screen's save starts failing with a 422.
UI_WRITTEN_KEYS: dict[str, tuple[str, ...]] = {
    "components/tabs/SettingsNotificationsTab.tsx": (
        "ntfy_enabled",
        "ntfy_server",
        "ntfy_topic",
        "ntfy_token",
        "gotify_enabled",
        "gotify_server",
        "gotify_token",
        "pushover_enabled",
        "pushover_user_key",
        "pushover_api_token",
        "slack_enabled",
        "slack_webhook_url",
        "discord_enabled",
        "discord_webhook_url",
        "matrix_enabled",
        "matrix_homeserver",
        "matrix_access_token",
        "matrix_room_id",
        "telegram_enabled",
        "telegram_bot_token",
        "telegram_chat_id",
        "telegram_inbound_enabled",
        "email_enabled",
        "email_smtp_host",
        "email_smtp_port",
        "email_smtp_user",
        "email_smtp_password",
        "email_smtp_tls",
        "email_from",
        "email_to",
        "notify_recalls",
        "notify_service_due",
        "notify_service_overdue",
        "notify_insurance_expiring",
        "notify_warranty_expiring",
        "notify_milestones",
        "notify_insurance_days",
        "notify_warranty_days",
        "notify_service_days",
        "notify_service_miles",
        "notify_def_low",
        "notify_def_low_threshold_percent",
        "notification_retry_attempts",
        "notification_retry_delay",
    ),
    "components/tabs/SettingsIntegrationsTab.tsx": (
        "nhtsa_enabled",
        "nhtsa_auto_check",
        "nhtsa_recall_check_interval",
        "nhtsa_recalls_api_url",
        "carcomplaints_enabled",
        "tomtom_api_key",
        "tomtom_enabled",
        "webhook_ingest_token",
        "llm_receipt_parse_enabled",
        "llm_garage_assistant_enabled",
        "llm_base_url",
        "llm_model",
        "llm_api_key",
    ),
    "components/tabs/SettingsFilesTab.tsx": (
        "max_upload_size_mb",
        "allowed_photo_types",
        "allowed_attachment_types",
        "window_sticker_enabled",
        "window_sticker_ocr_enabled",
    ),
    "components/tabs/SettingsSystemTab.tsx": (
        "timezone",
        "family_friends_enabled",
        "auto_archive_inactive_days",
        "auth_mode",
    ),
    "components/modals/FamilyManagementModal.tsx": ("multi_user_enabled",),
    "components/settings/InstanceUnitDefaultsCard.tsx": ("default_unit_prefs",),
    "e2e/household-timezone.spec.ts": ("timezone",),
}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("source", "key"),
    [(source, key) for source, keys in UI_WRITTEN_KEYS.items() for key in keys],
)
def test_every_key_a_settings_screen_writes_is_writable(source: str, key: str) -> None:
    """Control, passes on main's behaviour: the allowlist must not break a screen."""
    assert key in GENERIC_WRITABLE_KEYS, f"{source} writes {key}"


@pytest.mark.unit
@pytest.mark.parametrize(
    "key",
    [
        "app_version",
        "nhtsa_last_check",
        "telegram_update_offset",
        "livelink_telemetry_retention_days",
        "livelink_global_token_hash",
        "livelink_mqtt_broker_port",
        "effective_timezone",
        "theme",
        "app_name",
    ],
)
def test_system_typed_and_retired_keys_are_not_writable(key: str) -> None:
    assert key not in GENERIC_WRITABLE_KEYS


@pytest.mark.unit
def test_every_writable_key_fits_the_key_column() -> None:
    """Control. `Setting.key` is String(50): a longer key is a PostgreSQL 500."""
    width = Setting.__table__.c.key.type.length
    assert width is not None
    assert all(len(key) <= width for key in GENERIC_WRITABLE_KEYS)


@pytest.mark.unit
@pytest.mark.parametrize(
    "key",
    # `default_unit_prefs` has no static value: its row is derived at seed time.
    [key for key, meta in DEFAULT_SETTINGS.items() if "value" in meta],
)
def test_every_seeded_default_passes(key: str) -> None:
    """Control: a rule that refused a seed would 422 a fresh instance's first save."""
    check_setting_value(key, DEFAULT_SETTINGS[key]["value"])


@pytest.mark.unit
@pytest.mark.parametrize(
    ("key", "value"),
    [
        # A bare int() in create_pending_link (services/oidc/linking.py).
        ("oidc_link_token_expire_minutes", ""),
        ("oidc_link_token_expire_minutes", None),
        ("oidc_link_token_expire_minutes", "0"),
        ("oidc_link_token_expire_minutes", "five"),
        # attempt_count >= 0 refuses every link.
        ("oidc_link_max_password_attempts", "0"),
        ("oidc_link_max_password_attempts", "x"),
        # A bare int() in check_expiring_documents (tasks/scheduled.py).
        ("notify_insurance_days", "abc"),
        ("notify_insurance_days", "1.5"),
        ("notify_warranty_days", "abc"),
        # A bare float() on every send (notifications/dispatcher.py).
        ("notification_retry_delay", "abc"),
        ("notification_retry_delay", "inf"),
        ("notification_retry_delay", "nan"),
        ("auth_mode", "locall"),
        ("livelink_telemetry_retention_days", "0"),
        ("livelink_telemetry_retention_days", "-5"),
        ("livelink_telemetry_retention_days", "29"),
        ("livelink_telemetry_retention_days", "366"),
        ("livelink_telemetry_retention_days", "x"),
        ("livelink_telemetry_retention_days", ""),
    ],
)
def test_a_value_its_reader_cannot_use_is_refused(key: str, value: str | None) -> None:
    with pytest.raises(ValueError):
        check_setting_value(key, value)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("oidc_link_token_expire_minutes", "1"),
        ("oidc_link_token_expire_minutes", 5),
        # Its reader defaults a blank to 3.
        ("oidc_link_max_password_attempts", ""),
        ("oidc_link_max_password_attempts", None),
        # A cleared number field sends "", and the reader defaults it.
        ("notify_insurance_days", ""),
        ("notify_insurance_days", "45"),
        ("notify_warranty_days", ""),
        ("notification_retry_delay", ""),
        ("notification_retry_delay", "0.5"),
        ("notification_retry_delay", "3"),
        ("auth_mode", "local"),
        ("auth_mode", "OIDC"),
        ("auth_mode", ""),
        ("livelink_telemetry_retention_days", "30"),
        ("livelink_telemetry_retention_days", "365"),
        ("livelink_telemetry_retention_days", 90),
        # Lenient or unread: not checked, so a stored oddity never blocks a tab's save.
        ("notify_service_miles", "-1"),
        ("email_smtp_port", "not a port"),
        ("notify_def_low_threshold_percent", "banana"),
        ("max_upload_size_mb", "1.5"),
        ("ntfy_topic", "anything"),
    ],
)
def test_a_usable_value_passes(key: str, value: object) -> None:
    check_setting_value(key, value)

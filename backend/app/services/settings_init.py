"""Settings initialization service."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.models.settings import Setting

logger = logging.getLogger(__name__)

# Default settings with categories
DEFAULT_SETTINGS = {
    # Application settings
    "app_version": {
        "value": app_settings.app_version,
        "category": "general",
        "description": "Application version",
        "encrypted": False,
    },
    "debug_mode": {
        "value": "false",
        "category": "general",
        "description": "Enable debug mode for troubleshooting",
        "encrypted": False,
    },
    "auth_mode": {
        "value": "none",
        "category": "security",
        "description": "Authentication mode (none, local, oidc)",
        "encrypted": False,
    },
    # OIDC/SSO Authentication settings
    "oidc_enabled": {
        "value": "false",
        "category": "security",
        "description": "Enable OIDC/SSO authentication",
        "encrypted": False,
    },
    "oidc_provider_name": {
        "value": "",
        "category": "security",
        "description": "OIDC provider name (e.g., Authentik, Keycloak, Auth0)",
        "encrypted": False,
    },
    "oidc_issuer_url": {
        "value": "",
        "category": "security",
        "description": "OIDC issuer/discovery URL (e.g., https://auth.example.com/application/o/mygarage/)",
        "encrypted": False,
    },
    "oidc_client_id": {
        "value": "",
        "category": "security",
        "description": "OIDC client ID",
        "encrypted": False,
    },
    "oidc_client_secret": {
        "value": "",
        "category": "security",
        "description": "OIDC client secret",
        "encrypted": True,  # Must be encrypted!
    },
    "oidc_redirect_uri": {
        "value": "",
        "category": "security",
        "description": "OIDC redirect URI (callback URL, auto-generated if empty)",
        "encrypted": False,
    },
    "oidc_scopes": {
        "value": "openid profile email",
        "category": "security",
        "description": "OIDC scopes to request (space-separated)",
        "encrypted": False,
    },
    "oidc_auto_create_users": {
        "value": "true",
        "category": "security",
        "description": "Automatically create users from OIDC claims on first login",
        "encrypted": False,
    },
    "oidc_admin_group": {
        "value": "",
        "category": "security",
        "description": "OIDC group name for admin users (optional, checks 'groups' claim)",
        "encrypted": False,
    },
    "oidc_username_claim": {
        "value": "preferred_username",
        "category": "security",
        "description": "OIDC claim to use for username",
        "encrypted": False,
    },
    "oidc_email_claim": {
        "value": "email",
        "category": "security",
        "description": "OIDC claim to use for email address",
        "encrypted": False,
    },
    "oidc_name_claim": {
        "value": "name",
        "category": "security",
        "description": "OIDC claim to use for full name",
        "encrypted": False,
    },
    "oidc_link_token_expire_minutes": {
        "value": "5",
        "category": "security",
        "description": "Pending link token expiration in minutes for username-based account linking",
        "encrypted": False,
    },
    "oidc_link_max_password_attempts": {
        "value": "3",
        "category": "security",
        "description": "Maximum password attempts per pending link token for username-based account linking",
        "encrypted": False,
    },
    "multi_user_enabled": {
        "value": "false",
        "category": "security",
        "description": "Enable multi-user mode (allows creating additional users beyond first admin)",
        "encrypted": False,
    },
    "date_format": {
        "value": "MM/DD/YYYY",
        "category": "general",
        "description": "Date format for display",
        "encrypted": False,
    },
    "distance_unit": {
        "value": "miles",
        "category": "general",
        "description": "Distance unit (miles or km)",
        "encrypted": False,
    },
    "fuel_unit": {
        "value": "gallons",
        "category": "general",
        "description": "Fuel unit (gallons or liters)",
        "encrypted": False,
    },
    # File management settings
    "max_upload_size_mb": {
        "value": "10",
        "category": "files",
        "description": "Maximum file upload size in MB",
        "encrypted": False,
    },
    "allowed_photo_types": {
        "value": "jpg,jpeg,png,webp",
        "category": "files",
        "description": "Allowed photo file types",
        "encrypted": False,
    },
    "allowed_attachment_types": {
        "value": "pdf,jpg,jpeg,png,doc,docx",
        "category": "files",
        "description": "Allowed attachment file types",
        "encrypted": False,
    },
    # NHTSA Integration
    "nhtsa_enabled": {
        "value": "true",
        "category": "integrations",
        "description": "Enable NHTSA recall integration",
        "encrypted": False,
    },
    "nhtsa_auto_check": {
        "value": "true",
        "category": "integrations",
        "description": "Automatically check for recalls on schedule",
        "encrypted": False,
    },
    "nhtsa_recall_check_interval": {
        "value": "7",
        "category": "integrations",
        "description": "Days between automatic recall checks (default: weekly)",
        "encrypted": False,
    },
    "nhtsa_last_check": {
        "value": "",
        "category": "integrations",
        "description": "Timestamp of last NHTSA recall check",
        "encrypted": False,
    },
    "nhtsa_recalls_api_url": {
        "value": "https://api.nhtsa.gov/recalls",
        "category": "integrations",
        "description": "NHTSA Recalls API base URL",
        "encrypted": False,
    },
    # Window Sticker Integration
    "window_sticker_enabled": {
        "value": "true",
        "category": "integrations",
        "description": "Enable window sticker upload and OCR extraction",
        "encrypted": False,
    },
    "window_sticker_ocr_enabled": {
        "value": "true",
        "category": "integrations",
        "description": "Automatically extract data from uploaded window stickers using OCR",
        "encrypted": False,
    },
    # ============================================
    # Multi-Service Notification Settings
    # ============================================
    # Retry settings (global)
    "notification_retry_attempts": {
        "value": "3",
        "category": "notifications",
        "description": "Max retry attempts for high-priority notifications",
        "encrypted": False,
    },
    "notification_retry_delay": {
        "value": "2.0",
        "category": "notifications",
        "description": "Base delay between retry attempts (seconds)",
        "encrypted": False,
    },
    # ntfy service
    "ntfy_enabled": {
        "value": "false",
        "category": "notifications",
        "description": "Enable ntfy notifications",
        "encrypted": False,
    },
    "ntfy_server": {
        "value": "",
        "category": "notifications",
        "description": "ntfy server URL (e.g., https://ntfy.sh)",
        "encrypted": False,
    },
    "ntfy_topic": {
        "value": "mygarage",
        "category": "notifications",
        "description": "ntfy topic name",
        "encrypted": False,
    },
    "ntfy_token": {
        "value": "",
        "category": "notifications",
        "description": "ntfy API token (optional, for authentication)",
        "encrypted": True,
    },
    # Gotify service
    "gotify_enabled": {
        "value": "false",
        "category": "notifications",
        "description": "Enable Gotify notifications",
        "encrypted": False,
    },
    "gotify_server": {
        "value": "",
        "category": "notifications",
        "description": "Gotify server URL",
        "encrypted": False,
    },
    "gotify_token": {
        "value": "",
        "category": "notifications",
        "description": "Gotify application token",
        "encrypted": True,
    },
    # Pushover service
    "pushover_enabled": {
        "value": "false",
        "category": "notifications",
        "description": "Enable Pushover notifications",
        "encrypted": False,
    },
    "pushover_user_key": {
        "value": "",
        "category": "notifications",
        "description": "Pushover user key",
        "encrypted": True,
    },
    "pushover_api_token": {
        "value": "",
        "category": "notifications",
        "description": "Pushover API token",
        "encrypted": True,
    },
    # Slack service
    "slack_enabled": {
        "value": "false",
        "category": "notifications",
        "description": "Enable Slack notifications",
        "encrypted": False,
    },
    "slack_webhook_url": {
        "value": "",
        "category": "notifications",
        "description": "Slack incoming webhook URL",
        "encrypted": True,
    },
    # Discord service
    "discord_enabled": {
        "value": "false",
        "category": "notifications",
        "description": "Enable Discord notifications",
        "encrypted": False,
    },
    "discord_webhook_url": {
        "value": "",
        "category": "notifications",
        "description": "Discord webhook URL",
        "encrypted": True,
    },
    # Telegram service
    "telegram_enabled": {
        "value": "false",
        "category": "notifications",
        "description": "Enable Telegram notifications",
        "encrypted": False,
    },
    "telegram_bot_token": {
        "value": "",
        "category": "notifications",
        "description": "Telegram bot token from @BotFather",
        "encrypted": True,
    },
    "telegram_chat_id": {
        "value": "",
        "category": "notifications",
        "description": "Telegram chat/group/channel ID",
        "encrypted": False,
    },
    # Email service
    "email_enabled": {
        "value": "false",
        "category": "notifications",
        "description": "Enable email notifications",
        "encrypted": False,
    },
    "email_smtp_host": {
        "value": "",
        "category": "notifications",
        "description": "SMTP server hostname",
        "encrypted": False,
    },
    "email_smtp_port": {
        "value": "587",
        "category": "notifications",
        "description": "SMTP server port",
        "encrypted": False,
    },
    "email_smtp_user": {
        "value": "",
        "category": "notifications",
        "description": "SMTP username",
        "encrypted": False,
    },
    "email_smtp_password": {
        "value": "",
        "category": "notifications",
        "description": "SMTP password",
        "encrypted": True,
    },
    "email_smtp_tls": {
        "value": "true",
        "category": "notifications",
        "description": "Use STARTTLS for SMTP connection",
        "encrypted": False,
    },
    "email_from": {
        "value": "",
        "category": "notifications",
        "description": "Email from address",
        "encrypted": False,
    },
    "email_to": {
        "value": "",
        "category": "notifications",
        "description": "Email recipient address",
        "encrypted": False,
    },
    # Event notification toggles
    "notify_recalls": {
        "value": "true",
        "category": "notifications",
        "description": "Notify when new recalls are detected",
        "encrypted": False,
    },
    "notify_service_due": {
        "value": "true",
        "category": "notifications",
        "description": "Notify when service is due",
        "encrypted": False,
    },
    "notify_service_overdue": {
        "value": "true",
        "category": "notifications",
        "description": "Notify when service is overdue",
        "encrypted": False,
    },
    "notify_insurance_expiring": {
        "value": "true",
        "category": "notifications",
        "description": "Notify when insurance is expiring",
        "encrypted": False,
    },
    "notify_warranty_expiring": {
        "value": "true",
        "category": "notifications",
        "description": "Notify when warranty is expiring",
        "encrypted": False,
    },
    "notify_milestones": {
        "value": "false",
        "category": "notifications",
        "description": "Notify on odometer milestones",
        "encrypted": False,
    },
    "notify_insurance_days": {
        "value": "30",
        "category": "notifications",
        "description": "Days before insurance expiration to notify",
        "encrypted": False,
    },
    "notify_warranty_days": {
        "value": "30",
        "category": "notifications",
        "description": "Days before warranty expiration to notify",
        "encrypted": False,
    },
    "notify_service_days": {
        "value": "7",
        "category": "notifications",
        "description": "Days before service due to notify",
        "encrypted": False,
    },
    # CarComplaints Integration
    "carcomplaints_enabled": {
        "value": "true",
        "category": "integrations",
        "description": "Enable CarComplaints.com integration for vehicle issue research",
        "encrypted": False,
    },
    # TomTom Places API (Shop Discovery)
    "tomtom_enabled": {
        "value": "false",
        "category": "integrations",
        "description": "Enable TomTom Places API for shop discovery (falls back to OpenStreetMap)",
        "encrypted": False,
    },
    "tomtom_api_key": {
        "value": "",
        "category": "integrations",
        "description": "TomTom API key for Places API (2,500 free requests/day)",
        "encrypted": True,
    },
    # ============================================
    # LiveLink MQTT Settings
    # ============================================
    "livelink_mqtt_enabled": {
        "value": "false",
        "category": "livelink",
        "description": "Enable MQTT subscription for WiCAN devices (alternative to HTTPS POST)",
        "encrypted": False,
    },
    "livelink_mqtt_broker_host": {
        "value": "",
        "category": "livelink",
        "description": "MQTT broker hostname or IP address (e.g., 10.10.1.11 or mqtt.local)",
        "encrypted": False,
    },
    "livelink_mqtt_broker_port": {
        "value": "1883",
        "category": "livelink",
        "description": "MQTT broker port (default: 1883, TLS: 8883)",
        "encrypted": False,
    },
    "livelink_mqtt_username": {
        "value": "",
        "category": "livelink",
        "description": "MQTT broker username (optional, leave empty for anonymous)",
        "encrypted": False,
    },
    "livelink_mqtt_password": {
        "value": "",
        "category": "livelink",
        "description": "MQTT broker password (optional)",
        "encrypted": True,
    },
    "livelink_mqtt_topic_prefix": {
        "value": "wican",
        "category": "livelink",
        "description": "MQTT topic prefix (default: wican). Subscribes to {prefix}/{device_id}/#",
        "encrypted": False,
    },
    "livelink_mqtt_use_tls": {
        "value": "false",
        "category": "livelink",
        "description": "Use TLS/SSL for MQTT connection",
        "encrypted": False,
    },
}


async def initialize_default_settings(db: AsyncSession) -> None:
    """Initialize default settings if they don't exist.

    Args:
        db: Database session
    """
    logger.info("Checking and initializing default settings...")

    settings_added = 0
    settings_updated = 0

    for key, config in DEFAULT_SETTINGS.items():
        # Check if setting exists
        result = await db.execute(select(Setting).where(Setting.key == key))
        setting = result.scalar_one_or_none()

        if setting is None:
            # Create new setting
            setting = Setting(
                key=key,
                value=config["value"],
                category=config["category"],
                description=config["description"],
                encrypted=config["encrypted"],
            )
            db.add(setting)
            settings_added += 1
            logger.info("Added default setting: %s = %s", key, config["value"])
        else:
            # Update category and description if they don't match
            # (preserves user-modified values)
            needs_update = False

            if setting.category != config["category"]:
                setting.category = config["category"]
                needs_update = True

            if setting.description != config["description"]:
                setting.description = config["description"]
                needs_update = True

            if setting.encrypted != config["encrypted"]:
                setting.encrypted = config["encrypted"]
                needs_update = True

            # Special case: always update app_version
            if key == "app_version" and setting.value != app_settings.app_version:
                old_version = setting.value
                setting.value = app_settings.app_version
                needs_update = True
                logger.info(
                    "Updated app version: %s -> %s",
                    old_version,
                    app_settings.app_version,
                )

            if needs_update:
                settings_updated += 1

    await db.commit()

    logger.info(
        f"Settings initialization complete. Added: {settings_added}, Updated: {settings_updated}"
    )

"""Notification dispatcher for routing to enabled services."""

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.notifications.base import NotificationService
from app.services.notifications.ntfy import NtfyNotificationService
from app.services.notifications.gotify import GotifyNotificationService
from app.services.notifications.pushover import PushoverNotificationService
from app.services.notifications.slack import SlackNotificationService
from app.services.notifications.discord import DiscordNotificationService
from app.services.notifications.telegram import TelegramNotificationService
from app.services.notifications.email import EmailNotificationService
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)

# Event type to settings key mapping for MyGarage
# Format: "event_type": ("category_enabled_key", "specific_event_key")
EVENT_SETTINGS_MAP = {
    # Recall notifications
    "recall_detected": ("ntfy_enabled", "notify_recalls"),
    # Service/maintenance notifications
    "service_due": ("ntfy_enabled", "notify_service_due"),
    "service_overdue": ("ntfy_enabled", "notify_service_overdue"),
    # Insurance notifications
    "insurance_expiring": ("ntfy_enabled", "notify_insurance_expiring"),
    # Warranty notifications
    "warranty_expiring": ("ntfy_enabled", "notify_warranty_expiring"),
    # Milestone notifications
    "odometer_milestone": ("ntfy_enabled", "notify_milestones"),
}

# Priority mapping for different event types
EVENT_PRIORITY_MAP = {
    "recall_detected": "high",
    "service_due": "default",
    "service_overdue": "high",
    "insurance_expiring": "high",
    "warranty_expiring": "default",
    "odometer_milestone": "low",
}

# Tags mapping for different event types (emoji names for ntfy)
EVENT_TAGS_MAP = {
    "recall_detected": ["warning", "car"],
    "service_due": ["wrench", "calendar"],
    "service_overdue": ["warning", "wrench"],
    "insurance_expiring": ["page_facing_up", "warning"],
    "warranty_expiring": ["shield", "calendar"],
    "odometer_milestone": ["tada", "car"],
}


class NotificationDispatcher:
    """Routes notifications to enabled services with priority-based retry."""

    # Service-specific retry delay multipliers
    SERVICE_RETRY_MULTIPLIERS = {
        "discord": 1.5,
        "slack": 1.2,
        "telegram": 1.0,
        "ntfy": 1.0,
        "gotify": 1.0,
        "pushover": 1.0,
        "email": 2.0,
    }

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_setting(self, key: str, default: str = "") -> str:
        """Get a setting value."""
        setting = await SettingsService.get(self.db, key)
        return setting.value if setting and setting.value else default

    async def _get_setting_bool(self, key: str, default: bool = False) -> bool:
        """Get a boolean setting value."""
        value = await self._get_setting(key, str(default).lower())
        return value.lower() in ("true", "1", "yes")

    async def _get_setting_int(self, key: str, default: int = 0) -> int:
        """Get an integer setting value."""
        try:
            return int(await self._get_setting(key, str(default)))
        except ValueError:
            return default

    async def _is_event_enabled(self, event_type: str) -> bool:
        """Check if an event type is enabled in settings."""
        if event_type not in EVENT_SETTINGS_MAP:
            # Unknown event type - allow by default
            return True

        _, event_key = EVENT_SETTINGS_MAP[event_type]

        # Check if notifications are enabled at all (any service)
        any_service_enabled = await self._has_any_service_enabled()
        if not any_service_enabled:
            return False

        # Check specific event toggle
        event_enabled = await self._get_setting_bool(event_key, default=True)
        return event_enabled

    async def _has_any_service_enabled(self) -> bool:
        """Check if at least one notification service is enabled."""
        services = [
            "ntfy_enabled",
            "gotify_enabled",
            "pushover_enabled",
            "slack_enabled",
            "discord_enabled",
            "telegram_enabled",
            "email_enabled",
        ]
        for key in services:
            if await self._get_setting_bool(key, default=False):
                return True
        return False

    async def _get_enabled_services(self) -> list[NotificationService]:
        """Get list of enabled and configured notification services."""
        services: list[NotificationService] = []

        # Check ntfy
        if await self._get_setting_bool("ntfy_enabled", default=False):
            server = await self._get_setting("ntfy_server")
            topic = await self._get_setting("ntfy_topic", default="mygarage")
            api_key = await self._get_setting("ntfy_token")
            if server and topic:
                services.append(NtfyNotificationService(server, topic, api_key))

        # Check gotify
        if await self._get_setting_bool("gotify_enabled", default=False):
            server = await self._get_setting("gotify_server")
            token = await self._get_setting("gotify_token")
            if server and token:
                services.append(GotifyNotificationService(server, token))

        # Check pushover
        if await self._get_setting_bool("pushover_enabled", default=False):
            user_key = await self._get_setting("pushover_user_key")
            api_token = await self._get_setting("pushover_api_token")
            if user_key and api_token:
                services.append(PushoverNotificationService(user_key, api_token))

        # Check slack
        if await self._get_setting_bool("slack_enabled", default=False):
            webhook_url = await self._get_setting("slack_webhook_url")
            if webhook_url:
                services.append(SlackNotificationService(webhook_url))

        # Check discord
        if await self._get_setting_bool("discord_enabled", default=False):
            webhook_url = await self._get_setting("discord_webhook_url")
            if webhook_url:
                services.append(DiscordNotificationService(webhook_url))

        # Check telegram
        if await self._get_setting_bool("telegram_enabled", default=False):
            bot_token = await self._get_setting("telegram_bot_token")
            chat_id = await self._get_setting("telegram_chat_id")
            if bot_token and chat_id:
                services.append(TelegramNotificationService(bot_token, chat_id))

        # Check email
        if await self._get_setting_bool("email_enabled", default=False):
            smtp_host = await self._get_setting("email_smtp_host")
            smtp_port = await self._get_setting_int("email_smtp_port", default=587)
            smtp_user = await self._get_setting("email_smtp_user")
            smtp_password = await self._get_setting("email_smtp_password")
            from_address = await self._get_setting("email_from")
            to_address = await self._get_setting("email_to")
            use_tls = await self._get_setting_bool("email_smtp_tls", default=True)
            if (
                smtp_host
                and smtp_user
                and smtp_password
                and from_address
                and to_address
            ):
                services.append(
                    EmailNotificationService(
                        smtp_host,
                        smtp_port,
                        smtp_user,
                        smtp_password,
                        from_address,
                        to_address,
                        use_tls,
                    )
                )

        return services

    async def dispatch(
        self,
        event_type: str,
        title: str,
        message: str,
        priority: Optional[str] = None,
        tags: Optional[list[str]] = None,
        url: Optional[str] = None,
    ) -> dict[str, bool]:
        """
        Dispatch notification to all enabled services.

        Args:
            event_type: Type of event (e.g., "recall_detected", "service_due")
            title: Notification title
            message: Notification message body
            priority: Optional priority override (min, low, default, high, urgent)
            tags: Optional tags override for ntfy
            url: Optional URL to include in notification

        Returns:
            Dict mapping service names to success status
        """
        results: dict[str, bool] = {}

        # Check if event enabled
        if not await self._is_event_enabled(event_type):
            logger.debug("Event type '%s' is disabled", event_type)
            return results

        # Get enabled services
        services = await self._get_enabled_services()
        if not services:
            logger.debug("No notification services enabled")
            return results

        # Use default priority/tags if not provided
        final_priority = priority or EVENT_PRIORITY_MAP.get(event_type, "default")
        final_tags = tags or EVENT_TAGS_MAP.get(event_type, [])

        # Load global retry settings once
        max_attempts = await self._get_setting_int(
            "notification_retry_attempts", default=3
        )
        base_delay = float(
            await self._get_setting("notification_retry_delay", default="2.0")
        )

        # Send to all enabled services
        for service in services:
            try:
                # Adapt delay per service
                multiplier = self.SERVICE_RETRY_MULTIPLIERS.get(
                    service.service_name, 1.0
                )
                service_delay = base_delay * multiplier

                # Use retry for high-priority events, direct send for low-priority
                if final_priority in ("urgent", "high"):
                    success = await service.send_with_retry(
                        title=title,
                        message=message,
                        priority=final_priority,
                        tags=final_tags,
                        url=url,
                        max_attempts=max_attempts,
                        retry_delay=service_delay,
                    )
                else:
                    success = await service.send(
                        title=title,
                        message=message,
                        priority=final_priority,
                        tags=final_tags,
                        url=url,
                    )

                results[service.service_name] = success
            except Exception as e:
                logger.error("Error sending to %s: %s", service.service_name, e)
                results[service.service_name] = False
            finally:
                await service.close()

        return results

    # Convenience methods for MyGarage-specific notifications

    async def notify_recall_detected(
        self,
        vehicle_name: str,
        recall_count: int,
        url: Optional[str] = None,
    ) -> dict[str, bool]:
        """Send notification about new recalls detected."""
        return await self.dispatch(
            event_type="recall_detected",
            title=f"Recall Alert: {vehicle_name}",
            message=f"{recall_count} new recall(s) detected for {vehicle_name}. Please review and take appropriate action.",
            url=url,
        )

    async def notify_service_due(
        self,
        vehicle_name: str,
        service_type: str,
        days_until_due: int,
        url: Optional[str] = None,
    ) -> dict[str, bool]:
        """Send notification about upcoming service."""
        return await self.dispatch(
            event_type="service_due",
            title=f"Service Due: {vehicle_name}",
            message=f"{service_type} is due in {days_until_due} day(s) for {vehicle_name}.",
            url=url,
        )

    async def notify_service_overdue(
        self,
        vehicle_name: str,
        service_type: str,
        days_overdue: int,
        url: Optional[str] = None,
    ) -> dict[str, bool]:
        """Send notification about overdue service."""
        return await self.dispatch(
            event_type="service_overdue",
            title=f"Service Overdue: {vehicle_name}",
            message=f"{service_type} is {days_overdue} day(s) overdue for {vehicle_name}. Please schedule service soon.",
            url=url,
        )

    async def notify_insurance_expiring(
        self,
        vehicle_name: str,
        policy_name: str,
        days_until_expiry: int,
        url: Optional[str] = None,
    ) -> dict[str, bool]:
        """Send notification about expiring insurance."""
        return await self.dispatch(
            event_type="insurance_expiring",
            title=f"Insurance Expiring: {vehicle_name}",
            message=f"Insurance policy '{policy_name}' for {vehicle_name} expires in {days_until_expiry} day(s).",
            url=url,
        )

    async def notify_warranty_expiring(
        self,
        vehicle_name: str,
        warranty_name: str,
        days_until_expiry: int,
        url: Optional[str] = None,
    ) -> dict[str, bool]:
        """Send notification about expiring warranty."""
        return await self.dispatch(
            event_type="warranty_expiring",
            title=f"Warranty Expiring: {vehicle_name}",
            message=f"Warranty '{warranty_name}' for {vehicle_name} expires in {days_until_expiry} day(s).",
            url=url,
        )

    async def notify_odometer_milestone(
        self,
        vehicle_name: str,
        milestone: int,
        url: Optional[str] = None,
    ) -> dict[str, bool]:
        """Send notification about odometer milestone."""
        formatted_milestone = f"{milestone:,}"
        return await self.dispatch(
            event_type="odometer_milestone",
            title=f"Milestone Reached: {vehicle_name}",
            message=f"Congratulations! {vehicle_name} has reached {formatted_milestone} miles!",
            url=url,
        )

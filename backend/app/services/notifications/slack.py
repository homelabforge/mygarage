"""Slack notification service."""

import logging

import httpx

from app.services.notifications.base import NotificationService

logger = logging.getLogger(__name__)

# Map standard priorities to Slack colors
PRIORITY_COLORS = {
    "min": "#808080",  # Gray
    "low": "#36a64f",  # Green
    "default": "#2196F3",  # Blue
    "high": "#FF9800",  # Orange
    "urgent": "#F44336",  # Red
}


class SlackNotificationService(NotificationService):
    """Slack webhook notification service implementation."""

    service_name = "slack"

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url
        self.client = httpx.AsyncClient(timeout=10.0)

    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()

    async def send(
        self,
        title: str,
        message: str,
        priority: str = "default",
        tags: list[str] | None = None,
        url: str | None = None,
    ) -> bool:
        try:
            color = PRIORITY_COLORS.get(priority, "#2196F3")

            # Build attachment
            attachment = {
                "color": color,
                "title": title,
                "text": message,
                "footer": "MyGarage",
            }

            if url:
                attachment["title_link"] = url

            payload = {
                "attachments": [attachment],
            }

            response = await self.client.post(self.webhook_url, json=payload)
            response.raise_for_status()

            # Slack returns "ok" on success
            if response.text == "ok":
                logger.info("[slack] Sent notification: %s", title)
                return True

            logger.error("[slack] Unexpected response: %s", response.text)
            return False

        except httpx.HTTPStatusError as e:
            logger.error("[slack] HTTP error: %s", e)
            return False
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error("[slack] Connection error: %s", e)
            return False
        except (ValueError, KeyError) as e:
            logger.error("[slack] Invalid data: %s", e)
            return False

    async def test_connection(self) -> tuple[bool, str]:
        try:
            success = await self.send(
                title="MyGarage Test Notification",
                message="This is a test notification from MyGarage.",
                priority="low",
            )

            if success:
                return True, "Test notification sent successfully"
            return False, "Failed to send test notification"

        except Exception as e:
            return False, f"Connection test failed: {str(e)}"

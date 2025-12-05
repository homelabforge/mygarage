"""Discord notification service."""

import logging
from typing import Optional

import httpx

from app.services.notifications.base import NotificationService

logger = logging.getLogger(__name__)

# Map standard priorities to Discord embed colors (decimal)
PRIORITY_COLORS = {
    "min": 8421504,      # Gray (#808080)
    "low": 3580497,      # Green (#36a64f)
    "default": 2196943,  # Blue (#2196F3)
    "high": 16750848,    # Orange (#FF9800)
    "urgent": 16007990,  # Red (#F44336)
}


class DiscordNotificationService(NotificationService):
    """Discord webhook notification service implementation."""

    service_name = "discord"

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
        tags: Optional[list[str]] = None,
        url: Optional[str] = None,
    ) -> bool:
        try:
            color = PRIORITY_COLORS.get(priority, 2196943)

            # Build embed
            embed = {
                "title": title,
                "description": message,
                "color": color,
                "footer": {"text": "MyGarage"},
            }

            if url:
                embed["url"] = url

            payload = {
                "embeds": [embed],
            }

            response = await self.client.post(self.webhook_url, json=payload)

            # Discord returns 204 No Content on success
            if response.status_code == 204:
                logger.info("[discord] Sent notification: %s", title)
                return True

            response.raise_for_status()
            return False

        except httpx.HTTPStatusError as e:
            logger.error("[discord] HTTP error: %s", e)
            return False
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error("[discord] Connection error: %s", e)
            return False
        except (ValueError, KeyError) as e:
            logger.error("[discord] Invalid data: %s", e)
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

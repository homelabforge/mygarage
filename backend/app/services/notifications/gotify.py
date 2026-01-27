"""Gotify notification service."""

import logging

import httpx

from app.services.notifications.base import NotificationService

logger = logging.getLogger(__name__)

# Map standard priorities to Gotify scale (0-10)
PRIORITY_MAP = {
    "min": 1,
    "low": 3,
    "default": 5,
    "high": 7,
    "urgent": 10,
}


class GotifyNotificationService(NotificationService):
    """Gotify push notification service implementation."""

    service_name = "gotify"

    def __init__(
        self,
        server_url: str,
        app_token: str,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.app_token = app_token
        self.client = httpx.AsyncClient(
            timeout=10.0,
            headers={"X-Gotify-Key": app_token},
        )

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
            endpoint = f"{self.server_url}/message"

            gotify_priority = PRIORITY_MAP.get(priority, 5)

            payload: dict = {
                "title": title,
                "message": message,
                "priority": gotify_priority,
            }

            # Add click URL via extras if provided
            if url:
                payload["extras"] = {"client::notification": {"click": {"url": url}}}

            response = await self.client.post(endpoint, json=payload)
            response.raise_for_status()

            logger.info("[gotify] Sent notification: %s", title)
            return True

        except httpx.HTTPStatusError as e:
            logger.error("[gotify] HTTP error: %s", e)
            return False
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error("[gotify] Connection error: %s", e)
            return False
        except (ValueError, KeyError) as e:
            logger.error("[gotify] Invalid data: %s", e)
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

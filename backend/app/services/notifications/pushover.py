"""Pushover notification service."""

import logging
from typing import Optional

import httpx

from app.services.notifications.base import NotificationService

logger = logging.getLogger(__name__)

# Map standard priorities to Pushover scale (-2 to 2)
PRIORITY_MAP = {
    "min": -2,
    "low": -1,
    "default": 0,
    "high": 1,
    "urgent": 2,  # Note: urgent (2) requires retry/expire params
}


class PushoverNotificationService(NotificationService):
    """Pushover push notification service implementation."""

    service_name = "pushover"

    def __init__(
        self,
        user_key: str,
        api_token: str,
    ) -> None:
        self.user_key = user_key
        self.api_token = api_token
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
            endpoint = "https://api.pushover.net/1/messages.json"

            pushover_priority = PRIORITY_MAP.get(priority, 0)

            payload = {
                "token": self.api_token,
                "user": self.user_key,
                "title": title,
                "message": message,
                "priority": pushover_priority,
            }

            if url:
                payload["url"] = url

            # Emergency priority requires retry and expire
            if pushover_priority == 2:
                payload["retry"] = 60  # Retry every 60 seconds
                payload["expire"] = 3600  # Expire after 1 hour

            response = await self.client.post(endpoint, data=payload)
            response.raise_for_status()

            result = response.json()
            if result.get("status") == 1:
                logger.info("[pushover] Sent notification: %s", title)
                return True

            logger.error("[pushover] API error: %s", result)
            return False

        except httpx.HTTPStatusError as e:
            logger.error("[pushover] HTTP error: %s", e)
            return False
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error("[pushover] Connection error: %s", e)
            return False
        except (ValueError, KeyError) as e:
            logger.error("[pushover] Invalid data: %s", e)
            return False

    async def test_connection(self) -> tuple[bool, str]:
        try:
            # Use Pushover's validation endpoint first
            validate_endpoint = "https://api.pushover.net/1/users/validate.json"
            response = await self.client.post(
                validate_endpoint,
                data={
                    "token": self.api_token,
                    "user": self.user_key,
                },
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("status") == 1:
                    # Credentials valid, send test notification
                    success = await self.send(
                        title="MyGarage Test Notification",
                        message="This is a test notification from MyGarage.",
                        priority="low",
                    )
                    if success:
                        return True, "Test notification sent successfully"
                    return False, "Failed to send test notification"
                return False, f"Invalid credentials: {result.get('errors', [])}"

            return False, f"Validation failed with status {response.status_code}"

        except Exception as e:
            return False, f"Connection test failed: {str(e)}"

"""ntfy notification service."""

import logging
from typing import Optional

import httpx

from app.services.notifications.base import NotificationService

logger = logging.getLogger(__name__)


class NtfyNotificationService(NotificationService):
    """ntfy push notification service implementation."""

    service_name = "ntfy"

    def __init__(
        self,
        server_url: str,
        topic: str,
        api_key: Optional[str] = None,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.topic = topic
        self.headers: dict[str, str] = {}

        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

        self.client = httpx.AsyncClient(timeout=10.0, headers=self.headers)

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
            endpoint = f"{self.server_url}/{self.topic}"

            headers = self.headers.copy()
            if title:
                headers["Title"] = title
            if priority:
                headers["Priority"] = priority
            if tags:
                headers["Tags"] = ",".join(tags)
            if url:
                headers["Click"] = url

            response = await self.client.post(endpoint, content=message, headers=headers)
            response.raise_for_status()

            logger.info(f"[ntfy] Sent notification: {title}")
            return True

        except httpx.HTTPStatusError as e:
            logger.error(f"[ntfy] HTTP error: {e}")
            return False
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error(f"[ntfy] Connection error: {e}")
            return False
        except (ValueError, KeyError) as e:
            logger.error(f"[ntfy] Invalid data: {e}")
            return False

    async def test_connection(self) -> tuple[bool, str]:
        try:
            success = await self.send(
                title="MyGarage Test Notification",
                message="This is a test notification from MyGarage.",
                priority="low",
                tags=["white_check_mark", "car"],
            )

            if success:
                return True, "Test notification sent successfully"
            return False, "Failed to send test notification"

        except Exception as e:
            return False, f"Connection test failed: {str(e)}"

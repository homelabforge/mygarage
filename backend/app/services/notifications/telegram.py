"""Telegram notification service."""

import logging

import httpx

from app.services.notifications.base import NotificationService

logger = logging.getLogger(__name__)

# Map standard priorities to emoji indicators
PRIORITY_EMOJI = {
    "min": "",
    "low": "",
    "default": "",
    "high": "\u26a0\ufe0f ",  # Warning sign
    "urgent": "\ud83d\udea8 ",  # Rotating light
}


class TelegramNotificationService(NotificationService):
    """Telegram bot notification service implementation."""

    service_name = "telegram"

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
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
            endpoint = f"{self.base_url}/sendMessage"

            emoji = PRIORITY_EMOJI.get(priority, "")

            # Build message with HTML formatting
            text = f"{emoji}<b>{title}</b>\n\n{message}"

            if url:
                text += f'\n\n<a href="{url}">View Details</a>'

            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }

            response = await self.client.post(endpoint, json=payload)
            response.raise_for_status()

            result = response.json()
            if result.get("ok"):
                logger.info("[telegram] Sent notification: %s", title)
                return True

            logger.error("[telegram] API error: %s", result)
            return False

        except httpx.HTTPStatusError as e:
            logger.error("[telegram] HTTP error: %s", e)
            return False
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error("[telegram] Connection error: %s", e)
            return False
        except (ValueError, KeyError) as e:
            logger.error("[telegram] Invalid data: %s", e)
            return False

    async def test_connection(self) -> tuple[bool, str]:
        try:
            # First verify the bot token with getMe
            me_endpoint = f"{self.base_url}/getMe"
            response = await self.client.get(me_endpoint)

            if response.status_code != 200:
                return False, "Invalid bot token"

            result = response.json()
            if not result.get("ok"):
                return (
                    False,
                    f"Bot verification failed: {result.get('description', 'Unknown error')}",
                )

            # Now send test message
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

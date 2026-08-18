"""Matrix notification service (Client-Server API)."""

from __future__ import annotations

import logging
import uuid
from html import escape
from urllib.parse import quote

import httpx

from app.services.notifications.base import NotificationService

logger = logging.getLogger(__name__)


def _http_url(url: str | None) -> str | None:
    """Return ``url`` only when it is an http(s) link (safe for href)."""
    if not url:
        return None
    stripped = url.strip()
    lower = stripped.lower()
    if lower.startswith("https://") or lower.startswith("http://"):
        return stripped
    return None


def _formatted_body(title: str, message: str, url: str | None) -> str:
    """HTML body with user-controlled fields escaped."""
    html = f"<strong>{escape(title)}</strong><br/><br/>{escape(message)}"
    safe_url = _http_url(url)
    if safe_url:
        html += f'<br/><br/><a href="{escape(safe_url, quote=True)}">View Details</a>'
    return html


class MatrixNotificationService(NotificationService):
    """Send notifications as ``m.room.message`` events via Matrix C-S API."""

    service_name = "matrix"

    def __init__(
        self,
        homeserver: str,
        access_token: str,
        room_id: str,
    ) -> None:
        self.homeserver = homeserver.rstrip("/")
        self.access_token = access_token
        self.room_id = room_id
        self.client = httpx.AsyncClient(timeout=10.0)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def _send_url(self, txn_id: str) -> str:
        room = quote(self.room_id, safe="")
        txn = quote(txn_id, safe="")
        return f"{self.homeserver}/_matrix/client/v3/rooms/{room}/send/m.room.message/{txn}"

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
            payload = {
                "msgtype": "m.text",
                "body": f"{title}\n\n{message}" + (f"\n\n{url}" if url else ""),
                "format": "org.matrix.custom.html",
                "formatted_body": _formatted_body(title, message, url),
            }

            txn_id = uuid.uuid4().hex
            response = await self.client.put(
                self._send_url(txn_id),
                headers=self._headers(),
                json=payload,
            )

            if response.status_code in (200, 201):
                logger.info("[matrix] Sent notification: %s", title)
                return True

            response.raise_for_status()
            return False

        except httpx.HTTPStatusError as e:
            logger.error("[matrix] HTTP error: %s", e)
            return False
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error("[matrix] Connection error: %s", e)
            return False
        except (ValueError, KeyError) as e:
            logger.error("[matrix] Invalid data: %s", e)
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

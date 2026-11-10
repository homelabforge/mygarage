"""A failed notification logs no secret, and neither does its connection test."""

import logging

import httpx
import pytest

from app.services.notifications.base import NotificationService
from app.services.notifications.discord import DiscordNotificationService
from app.services.notifications.gotify import GotifyNotificationService
from app.services.notifications.matrix import MatrixNotificationService
from app.services.notifications.ntfy import NtfyNotificationService
from app.services.notifications.pushover import PushoverNotificationService
from app.services.notifications.slack import SlackNotificationService
from app.services.notifications.telegram import TelegramNotificationService

SECRET = "SECRET-7f3a"

SERVICES = {
    "telegram": lambda: TelegramNotificationService(bot_token=f"123456:{SECRET}", chat_id="42"),
    "discord": lambda: DiscordNotificationService(
        webhook_url=f"https://discord.com/api/webhooks/1/{SECRET}"
    ),
    "slack": lambda: SlackNotificationService(
        webhook_url=f"https://hooks.slack.com/services/T/B/{SECRET}"
    ),
    "gotify": lambda: GotifyNotificationService(
        server_url="https://gotify.example", app_token=SECRET
    ),
    "ntfy": lambda: NtfyNotificationService(server_url="https://ntfy.example", topic=SECRET),
    "matrix": lambda: MatrixNotificationService(
        homeserver="https://matrix.example", access_token=SECRET, room_id="!room:example"
    ),
    "pushover": lambda: PushoverNotificationService(user_key=SECRET, api_token=SECRET),
}


def _with_transport(service: NotificationService, handler) -> NotificationService:
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))  # pyright: ignore[reportAttributeAccessIssue]  # every backend here has a client
    return service


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(SERVICES))
async def test_a_rejected_send_logs_no_secret(name, caplog):
    caplog.set_level(logging.DEBUG)
    service = _with_transport(
        SERVICES[name](),
        lambda request: httpx.Response(400, json={"ok": False, "description": "Bad Request"}),
    )
    try:
        assert await service.send("Title", "Body") is False
    finally:
        await service.close()

    assert SECRET not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(SERVICES))
async def test_a_failed_connection_test_names_no_secret(name, caplog):
    def fail(request: httpx.Request) -> httpx.Response:
        response = httpx.Response(500, request=request)
        response.raise_for_status()
        return response

    caplog.set_level(logging.DEBUG)
    service = _with_transport(SERVICES[name](), fail)
    try:
        _ok, message = await service.test_connection()
    finally:
        await service.close()

    assert SECRET not in message
    assert SECRET not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(SERVICES))
async def test_an_error_send_does_not_catch_names_no_secret(name):
    """``send`` catches status, connect and timeout errors; a protocol error
    reaches ``test_connection``'s own catch-all, which must not print it."""

    def drop(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError(f"peer closed {request.url}", request=request)

    service = _with_transport(SERVICES[name](), drop)
    try:
        _ok, message = await service.test_connection()
    finally:
        await service.close()

    assert message == "Connection test failed: RemoteProtocolError"


class _Raising(NotificationService):
    """``send``, ``test_connection`` and ``close`` are all abstract on the base."""

    service_name = "raising"

    async def send(self, title, message, priority="default", tags=None, url=None) -> bool:
        response = httpx.Response(
            500, request=httpx.Request("POST", f"https://hook.example/{SECRET}")
        )
        response.raise_for_status()
        return True

    async def test_connection(self) -> tuple[bool, str]:
        return False, "unused"

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_the_retry_log_names_no_secret(caplog):
    caplog.set_level(logging.DEBUG)
    assert await _Raising().send_with_retry("T", "B", max_attempts=1, retry_delay=0) is False
    assert SECRET not in caplog.text

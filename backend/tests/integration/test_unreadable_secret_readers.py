"""What each secret reader does with a secret that can't be decrypted (D3a, R1-M1).

Plan test 15. Where a credential is optional (ntfy, the LLM, MQTT), None means
"connect without auth", so an unreadable secret must stop the call instead of
silently dropping the auth. Each test proves both halves on the same reader: an
unreadable secret makes no outbound call, and a configured-but-blank one still
connects without auth. The ntfy and MQTT test routes answer 200 with their own
failure envelope carrying the re-enter advice (R2-1).

Where a credential is required, the reader already stops on None. One test per
reader proves no outbound call happens and nothing garbled is used.

"Unreadable" is seeded as a real ciphertext bound to another key name, so it is
well-formed and fails only on the associated data.
"""

import logging
from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Setting
from app.routes.webhooks import require_webhook_token
from app.services import llm_client
from app.services.mqtt_subscriber import MQTTSubscriber
from app.services.notifications.dispatcher import NotificationDispatcher
from app.services.oidc.config import get_oidc_config
from app.services.poi.registry import POIProviderRegistry
from app.services.shop_discovery import ShopDiscoveryService
from app.utils.settings_crypto import encrypt

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

Keep = Callable[..., Awaitable[None]]
REENTER = "can't be decrypted; re-enter it"


def _unreadable(key: str) -> str:
    """A well-formed ciphertext that won't open under `key` (bound to another name)."""
    return encrypt(f"not_{key}", "the-real-secret")


async def _seed(db: AsyncSession, keep: Keep, rows: dict[str, str]) -> None:
    """Store raw column values, keeping the originals for teardown."""
    await keep(*rows)
    await db.execute(delete(Setting).where(Setting.key.in_(list(rows))))
    for key, raw in rows.items():
        db.add(Setting(key=key, stored_value=raw))
    await db.commit()


async def _set_raw(db: AsyncSession, key: str, raw: str) -> None:
    row = await db.get(Setting, key)
    assert row is not None
    row.stored_value = raw
    await db.commit()


def _http_mock(json_body: object = None) -> tuple[MagicMock, AsyncMock]:
    """A patched httpx.AsyncClient class and its instance's post()."""
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value=json_body)
    instance = AsyncMock()
    instance.post = AsyncMock(return_value=response)
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=None)
    cls = MagicMock(return_value=instance)
    return cls, instance.post


# --------------------------------------------------------------------------- ntfy


NTFY = {
    "ntfy_enabled": "true",
    "ntfy_server": "https://ntfy.example.com",
    "ntfy_topic": "garage",
}


async def test_the_dispatcher_skips_ntfy_with_an_unreadable_token(
    db_session: AsyncSession, keep_rows: Keep, caplog: pytest.LogCaptureFixture
) -> None:
    await _seed(db_session, keep_rows, {**NTFY, "ntfy_token": _unreadable("ntfy_token")})
    dispatcher = NotificationDispatcher(db_session)

    with (
        patch("app.services.notifications.dispatcher.NtfyNotificationService") as ntfy,
        caplog.at_level(logging.ERROR),
    ):
        await dispatcher._get_enabled_services()  # pyright: ignore[reportPrivateUsage]
        ntfy.assert_not_called()
        assert any(
            r.levelno == logging.ERROR and "ntfy_token" in r.getMessage() for r in caplog.records
        )
        assert "the-real-secret" not in caplog.text
        assert "enc:v1:" not in caplog.text

        # Configured without a token: still sends, without auth.
        await _set_raw(db_session, "ntfy_token", "")
        await dispatcher._get_enabled_services()  # pyright: ignore[reportPrivateUsage]
        ntfy.assert_called_once()
        assert not ntfy.call_args.args[2]


async def test_the_ntfy_test_route_returns_the_re_enter_envelope(
    client: AsyncClient, auth_headers, db_session: AsyncSession, keep_rows: Keep
) -> None:
    await _seed(db_session, keep_rows, {**NTFY, "ntfy_token": _unreadable("ntfy_token")})
    cls, post = _http_mock()

    with patch("app.routes.notifications.httpx.AsyncClient", cls):
        response = await client.post("/api/notifications/test/ntfy", headers=auth_headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["success"] is False
        assert REENTER in body["message"]
        assert "ntfy token" in body["message"]
        post.assert_not_called()

        await _set_raw(db_session, "ntfy_token", "")
        response = await client.post("/api/notifications/test/ntfy", headers=auth_headers)
        assert response.json()["success"] is True, response.text
        post.assert_called_once()
        assert "Authorization" not in post.call_args.kwargs["headers"]


# --------------------------------------------------------------------------- LLM


async def test_the_llm_client_stops_on_an_unreadable_key(
    db_session: AsyncSession, keep_rows: Keep
) -> None:
    await _seed(
        db_session,
        keep_rows,
        {"llm_base_url": "https://llm.example.com/v1", "llm_api_key": _unreadable("llm_api_key")},
    )
    cls, post = _http_mock({"choices": [{"message": {"content": "ok"}}]})

    with patch("app.services.llm_client.httpx.AsyncClient", cls):
        with pytest.raises(HTTPException) as caught:
            await llm_client.chat_completion(db_session, system="s", user="u")
        assert REENTER in str(caught.value.detail)
        assert "LLM API key" in str(caught.value.detail)
        post.assert_not_called()

        await _set_raw(db_session, "llm_api_key", "")
        assert await llm_client.chat_completion(db_session, system="s", user="u") == "ok"
        post.assert_called_once()
        assert "Authorization" not in post.call_args.kwargs["headers"]


# --------------------------------------------------------------------------- MQTT


MQTT = {
    "livelink_mqtt_enabled": "true",
    "livelink_mqtt_broker_host": "mqtt.example.com",
    "livelink_mqtt_username": "",
}


async def test_the_mqtt_subscriber_stops_on_an_unreadable_password(
    db_session: AsyncSession,
    keep_rows: Keep,
    test_sessionmaker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _seed(
        db_session,
        keep_rows,
        {**MQTT, "livelink_mqtt_password": _unreadable("livelink_mqtt_password")},
    )
    subscriber = MQTTSubscriber()

    with (
        patch("app.services.mqtt_subscriber.AsyncSessionLocal", test_sessionmaker),
        caplog.at_level(logging.ERROR),
    ):
        assert await subscriber._get_config() is None  # pyright: ignore[reportPrivateUsage]
        assert any(
            r.levelno == logging.ERROR and "livelink_mqtt_password" in r.getMessage()
            for r in caplog.records
        )
        assert "the-real-secret" not in caplog.text

        # Configured without a password: connects anonymously.
        await _set_raw(db_session, "livelink_mqtt_password", "")
        config = await subscriber._get_config()  # pyright: ignore[reportPrivateUsage]
        assert config is not None
        assert config["host"] == "mqtt.example.com"
        assert config["password"] is None


async def test_the_mqtt_test_route_returns_the_re_enter_envelope(
    client: AsyncClient, auth_headers, db_session: AsyncSession, keep_rows: Keep
) -> None:
    await _seed(
        db_session,
        keep_rows,
        {**MQTT, "livelink_mqtt_password": _unreadable("livelink_mqtt_password")},
    )

    with patch("aiomqtt.Client") as mqtt_client:
        response = await client.post("/api/livelink/mqtt/test", headers=auth_headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["success"] is False
        assert REENTER in body["message"]
        assert "MQTT password" in body["message"]
        assert body["broker"] == "mqtt.example.com:1883"
        mqtt_client.assert_not_called()

        await _set_raw(db_session, "livelink_mqtt_password", "")
        response = await client.post("/api/livelink/mqtt/test", headers=auth_headers)
        assert response.json()["success"] is True, response.text
        mqtt_client.assert_called_once()
        assert mqtt_client.call_args.kwargs["password"] is None


# --------------------------------------------------------------- required credentials


# (enable switch, the secret, the other settings the service needs)
DISPATCHED = {
    "gotify": ("gotify_enabled", "gotify_token", {"gotify_server": "https://gotify.example"}),
    "pushover_user": (
        "pushover_enabled",
        "pushover_user_key",
        {"pushover_api_token": "app-token"},
    ),
    "pushover_app": ("pushover_enabled", "pushover_api_token", {"pushover_user_key": "user"}),
    "slack": ("slack_enabled", "slack_webhook_url", {}),
    "discord": ("discord_enabled", "discord_webhook_url", {}),
    "matrix": (
        "matrix_enabled",
        "matrix_access_token",
        {"matrix_homeserver": "https://matrix.example", "matrix_room_id": "!room:example"},
    ),
    "telegram": ("telegram_enabled", "telegram_bot_token", {"telegram_chat_id": "42"}),
    "email": (
        "email_enabled",
        "email_smtp_password",
        {
            "email_smtp_host": "smtp.example.com",
            "email_smtp_user": "garage",
            "email_from": "garage@example.com",
            "email_to": "me@example.com",
        },
    ),
}


@pytest.mark.parametrize("service", list(DISPATCHED))
async def test_the_dispatcher_builds_no_service_on_an_unreadable_required_secret(
    service: str, db_session: AsyncSession, keep_rows: Keep
) -> None:
    switch, secret, others = DISPATCHED[service]
    await _seed(db_session, keep_rows, {switch: "true", secret: _unreadable(secret), **others})

    built = await NotificationDispatcher(db_session)._get_enabled_services()  # pyright: ignore[reportPrivateUsage]

    prefix = switch.removesuffix("_enabled")
    assert not [s for s in built if type(s).__module__.endswith(f".{prefix}")]


POI = {
    "tomtom": "tomtom_api_key",
    "google_places": "google_places_api_key",
    "yelp": "yelp_api_key",
    "foursquare": "foursquare_api_key",
}


async def test_the_poi_registry_configures_no_provider_on_an_unreadable_key(
    db_session: AsyncSession, keep_rows: Keep
) -> None:
    rows = {f"{name}_enabled": "true" for name in POI}
    rows |= {key: _unreadable(key) for key in POI.values()}
    await _seed(db_session, keep_rows, rows)

    configs = await POIProviderRegistry(db_session)._load_provider_configs()  # pyright: ignore[reportPrivateUsage]

    assert [c["name"] for c in configs] == ["osm"]


async def test_shop_discovery_leaves_tomtom_off_on_an_unreadable_key(
    db_session: AsyncSession, keep_rows: Keep
) -> None:
    await _seed(
        db_session,
        keep_rows,
        {"tomtom_enabled": "true", "tomtom_api_key": _unreadable("tomtom_api_key")},
    )
    service = ShopDiscoveryService(db_session)

    await service._load_settings()  # pyright: ignore[reportPrivateUsage]

    assert service.tomtom_enabled is False
    assert service.tomtom_api_key == ""


async def test_an_unreadable_webhook_token_is_a_503_not_a_match(
    db_session: AsyncSession, keep_rows: Keep
) -> None:
    stored = _unreadable("webhook_ingest_token")
    await _seed(db_session, keep_rows, {"webhook_ingest_token": stored})

    for provided in (stored, "", "the-real-secret"):
        with pytest.raises(HTTPException) as caught:
            await require_webhook_token(db_session, provided)
        assert caught.value.status_code == 503


async def test_oidc_sends_no_ciphertext_for_an_unreadable_client_secret(
    db_session: AsyncSession, keep_rows: Keep
) -> None:
    await _seed(db_session, keep_rows, {"oidc_client_secret": _unreadable("oidc_client_secret")})

    config = await get_oidc_config(db_session)

    assert config["client_secret"] == ""
    assert not [v for v in config.values() if "enc:v1:" in v]

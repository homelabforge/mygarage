"""`PUT /mqtt/settings` applies what it saved (R3, B-1).

The drawer's "Enable MQTT subscription" switch used to only write the setting.
The subscriber reads its config once per connection and then blocks in its
message loop, so switching it off did nothing until a restart and the card
stayed green.

These drive the real singleton's stop path. `start_mqtt_subscriber` reads the
switch through its own `AsyncSessionLocal`, which is bound to the test database
here so it sees what the route committed; only the subscriber's own `start`
(which would open a broker connection) is replaced.
"""

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.services.mqtt_subscriber import mqtt_subscriber
from tests.integration._secret_helpers import Keep, seed_rows

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

URL = "/api/livelink/mqtt/settings"

MQTT = {
    "livelink_mqtt_enabled": "true",
    "livelink_mqtt_broker_host": "mqtt.example.com",
    "livelink_mqtt_broker_port": "1883",
    "livelink_mqtt_username": "",
    "livelink_mqtt_password": "",
    "livelink_mqtt_topic_prefix": "wican",
    "livelink_mqtt_use_tls": "false",
}


@pytest_asyncio.fixture
async def running() -> AsyncGenerator[asyncio.Task[None]]:
    """The singleton, looking like it's mid-connection.

    Its task just sleeps, so `stop()` cancelling it is the only way it ends.
    """
    task: asyncio.Task[None] = asyncio.create_task(asyncio.sleep(3600))
    mqtt_subscriber._running = True  # pyright: ignore[reportPrivateUsage]
    mqtt_subscriber._task = task  # pyright: ignore[reportPrivateUsage]
    yield task
    task.cancel()
    mqtt_subscriber._running = False  # pyright: ignore[reportPrivateUsage]
    mqtt_subscriber._task = None  # pyright: ignore[reportPrivateUsage]


@pytest_asyncio.fixture
async def idle() -> AsyncGenerator[None]:
    """The singleton stopped, and put back stopped."""
    mqtt_subscriber._running = False  # pyright: ignore[reportPrivateUsage]
    mqtt_subscriber._task = None  # pyright: ignore[reportPrivateUsage]
    yield
    mqtt_subscriber._running = False  # pyright: ignore[reportPrivateUsage]
    mqtt_subscriber._task = None  # pyright: ignore[reportPrivateUsage]


@pytest.fixture
def start(test_sessionmaker):
    """The subscriber's `start`, recorded instead of connecting."""
    with (
        patch("app.tasks.livelink_tasks.AsyncSessionLocal", test_sessionmaker),
        patch.object(mqtt_subscriber, "start", new=AsyncMock()) as started,
    ):
        yield started


async def test_switching_mqtt_off_stops_the_subscriber_within_the_request(
    client, auth_headers, db_session, keep_rows: Keep, running, start
):
    await seed_rows(db_session, keep_rows, MQTT)

    response = await client.put(URL, json={"enabled": False}, headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is False
    assert running.cancelled()
    assert mqtt_subscriber.is_running is False
    start.assert_not_awaited()


async def test_switching_mqtt_on_starts_the_subscriber(
    client, auth_headers, db_session, keep_rows: Keep, idle, start
):
    await seed_rows(db_session, keep_rows, {**MQTT, "livelink_mqtt_enabled": "false"})

    response = await client.put(URL, json={"enabled": True}, headers=auth_headers)

    assert response.status_code == 200, response.text
    start.assert_awaited_once()


async def test_a_broker_change_restarts_a_running_subscriber(
    client, auth_headers, db_session, keep_rows: Keep, running, start
):
    """Same as the drawer's Restart button: the new host only applies on a new connection."""
    await seed_rows(db_session, keep_rows, MQTT)

    response = await client.put(
        URL, json={"broker_host": "broker.example.net"}, headers=auth_headers
    )

    assert response.status_code == 200, response.text
    assert running.cancelled()
    start.assert_awaited_once()


async def test_a_new_topic_prefix_restarts_a_running_subscriber(
    client, auth_headers, db_session, keep_rows: Keep, running, start
):
    await seed_rows(db_session, keep_rows, MQTT)

    response = await client.put(URL, json={"topic_prefix": "car"}, headers=auth_headers)

    assert response.status_code == 200, response.text
    assert running.cancelled()
    start.assert_awaited_once()


async def test_a_save_that_changes_nothing_leaves_the_subscriber_alone(
    client, auth_headers, db_session, keep_rows: Keep, running, start
):
    """Regression guard: resending the stored values isn't a change, so no reconnect."""
    await seed_rows(db_session, keep_rows, MQTT)

    response = await client.put(
        URL,
        json={"enabled": True, "broker_host": "mqtt.example.com", "broker_port": 1883},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    assert not running.cancelled()
    start.assert_not_awaited()


async def test_a_broker_change_does_not_start_a_stopped_subscriber(
    client, auth_headers, db_session, keep_rows: Keep, idle, start
):
    """Regression guard: only a running subscriber is restarted; the switch starts one."""
    await seed_rows(db_session, keep_rows, MQTT)

    response = await client.put(
        URL, json={"broker_host": "broker.example.net"}, headers=auth_headers
    )

    assert response.status_code == 200, response.text
    start.assert_not_awaited()

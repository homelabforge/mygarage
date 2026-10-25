"""Discovery is bounded. Every limit is enforced server-side."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.settings_service import reenter_message
from tests.integration._secret_helpers import seed_rows, unreadable_ciphertext

URL = "/api/livelink/topic-discovery"


@pytest.mark.asyncio
async def test_returns_observed_topics_with_samples(client, auth_headers):
    with patch(
        "app.routes.livelink_admin.mqtt_subscriber.discover_topics",
        new=AsyncMock(return_value=[{"topic": "mygarage/rv/status", "sample": "online"}]),
    ):
        resp = await client.post(URL, json={"prefix": "mygarage/rv/#"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()[0]["topic"] == "mygarage/rv/status"


@pytest.mark.asyncio
async def test_an_out_of_range_duration_is_rejected_by_the_schema(client, auth_headers):
    """The schema is the contract: ge=1, le=60. 9999 is a 422, not a clamp."""
    resp = await client.post(URL, json={"prefix": "a/#", "seconds": 9999}, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_the_service_clamps_defensively_for_non_http_callers():
    """Belt and braces: the service is also callable from a task or shell."""
    from app.services.mqtt_subscriber import MAX_DISCOVERY_SECONDS, MQTTSubscriber

    sub = MQTTSubscriber()
    sub._discovering = True  # forces the guard before any network work
    with pytest.raises(RuntimeError):
        await sub.discover_topics(prefix="a/#", seconds=9999)
    assert MAX_DISCOVERY_SECONDS == 60


@pytest.mark.asyncio
async def test_a_concurrent_sniff_is_refused(client, auth_headers):
    with patch(
        "app.routes.livelink_admin.mqtt_subscriber.discover_topics",
        new=AsyncMock(side_effect=RuntimeError("A discovery run is already in progress")),
    ):
        resp = await client.post(URL, json={"prefix": "a/#"}, headers=auth_headers)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_non_admins_are_refused(client, non_admin_headers):
    resp = await client.post(URL, json={"prefix": "a/#"}, headers=non_admin_headers)
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_topic_cap_and_payload_truncation():
    """Unit-level: the collector itself must bound what it keeps."""
    from app.services.mqtt_subscriber import _DiscoveryCollector

    c = _DiscoveryCollector(max_topics=2, max_sample=4)
    c.observe("a", b"0123456789")
    c.observe("b", b"xy")
    c.observe("c", b"z")
    assert len(c.results()) == 2
    assert c.results()[0]["sample"] == "0123"


def test_collector_keeps_one_sample_per_topic():
    from app.services.mqtt_subscriber import _DiscoveryCollector

    c = _DiscoveryCollector(max_topics=10, max_sample=16)
    c.observe("a", b"first")
    c.observe("a", b"second")
    assert len(c.results()) == 1
    assert c.results()[0]["sample"] == "first"


# ---------------------------------------------------------------------------
# B-4: a run that can't happen says why
# ---------------------------------------------------------------------------

_MQTT = {
    "livelink_mqtt_enabled": "true",
    "livelink_mqtt_broker_host": "mqtt.example.com",
    "livelink_mqtt_broker_port": "1883",
    "livelink_mqtt_username": "",
    "livelink_mqtt_password": "",
}


@pytest.fixture
def subscriber_db(test_sessionmaker):
    """`_get_config` opens its own session; point it at the test database."""
    with (
        patch("app.services.mqtt_subscriber.AsyncSessionLocal", test_sessionmaker),
        patch("app.services.mqtt_subscriber.load_household_zone", new=AsyncMock()),
    ):
        yield


@pytest.mark.asyncio
async def test_discovery_with_mqtt_off_is_409_saying_so(
    client, auth_headers, db_session, keep_rows, subscriber_db
):
    """It used to answer 200 with no topics, which reads as "nothing is publishing"."""
    await seed_rows(db_session, keep_rows, {**_MQTT, "livelink_mqtt_enabled": "false"})

    resp = await client.post(URL, json={"prefix": "a/#", "seconds": 1}, headers=auth_headers)

    assert resp.status_code == 409, resp.text
    assert "MQTT is off" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_discovery_with_no_broker_host_is_409_saying_so(
    client, auth_headers, db_session, keep_rows, subscriber_db
):
    await seed_rows(db_session, keep_rows, {**_MQTT, "livelink_mqtt_broker_host": ""})

    resp = await client.post(URL, json={"prefix": "a/#", "seconds": 1}, headers=auth_headers)

    assert resp.status_code == 409, resp.text
    assert "broker host" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_discovery_with_an_unreadable_password_is_409_saying_so(
    client, auth_headers, db_session, keep_rows, subscriber_db
):
    """Optional credential, so None would mean "connect anonymously". It stops
    with the re-enter advice instead, and never opens a connection.

    Regression guard for T9's B-4 change (green on 9e7b0e8e, red before it)."""
    await seed_rows(
        db_session,
        keep_rows,
        {**_MQTT, "livelink_mqtt_password": unreadable_ciphertext("livelink_mqtt_password")},
    )

    with patch("aiomqtt.Client") as mqtt_client:
        resp = await client.post(URL, json={"prefix": "a/#", "seconds": 1}, headers=auth_headers)

    assert resp.status_code == 409, resp.text
    assert reenter_message("MQTT password") in resp.json()["detail"]
    mqtt_client.assert_not_called()


@pytest.mark.asyncio
async def test_a_broker_that_refuses_is_502_with_its_message(
    client, auth_headers, db_session, keep_rows, subscriber_db
):
    """aiomqtt's error isn't a RuntimeError, so it used to escape the route as a 500."""
    import aiomqtt

    await seed_rows(db_session, keep_rows, _MQTT)

    class _Refused:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            raise aiomqtt.MqttError("[code:5] Connection refused: not authorised")

        async def __aexit__(self, *_exc) -> bool:
            return False

    with patch("aiomqtt.Client", _Refused):
        resp = await client.post(URL, json={"prefix": "a/#", "seconds": 1}, headers=auth_headers)

    assert resp.status_code == 502, resp.text
    assert "Connection refused: not authorised" in resp.json()["detail"]
    # The guard is released, so the next run isn't refused as "in progress".
    from app.services.mqtt_subscriber import mqtt_subscriber

    assert mqtt_subscriber._discovering is False  # pyright: ignore[reportPrivateUsage]

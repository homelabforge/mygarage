"""Subscriber dispatch and resubscribe. The WiCAN behavior gate is the existing suite."""

import asyncio
import contextlib
from unittest.mock import AsyncMock, patch

import pytest

from app.services.livelink_sources.base import BaseSourceModule, Capability, IngestBatch
from app.services.mqtt_subscriber import MQTTSubscriber

# LiveLink's master switch gates the ingest pipeline and SD backfill, and it is
# off by default. Explicit, not inherited from whatever an earlier test left in
# the shared database.
pytestmark = pytest.mark.usefixtures("livelink_enabled")


class _Spy(BaseSourceModule):
    kind = "spy"
    capabilities = frozenset({Capability.TELEMETRY})

    def __init__(self):
        self.seen = []

    async def subscriptions(self, db):
        return ["spy/one"]

    async def parse(self, env):
        self.seen.append(env.topic)
        return IngestBatch(device_key="x")


@contextlib.contextmanager
def _session_factory(db_session):
    """Bind `_process_message`'s own session factory to the test session.

    `_process_message` opens `AsyncSessionLocal()` itself, which resolves to
    the configured database rather than the test one (`unable to open database
    file`). The old `_handle_*` handlers took a session argument and so never
    hit this; dispatch owns the transaction now, so the factory is what the
    test has to replace.
    """

    @contextlib.asynccontextmanager
    async def _factory():
        yield db_session

    with (
        patch("app.services.mqtt_subscriber.AsyncSessionLocal", _factory),
        patch("app.services.mqtt_subscriber.load_household_zone", new=AsyncMock()),
    ):
        yield


@pytest.mark.asyncio
async def test_a_message_is_dispatched_to_its_owning_module(db_session):
    sub = MQTTSubscriber()
    spy = _Spy()
    sub._subscribed = {"spy/one": spy}
    with (
        _session_factory(db_session),
        patch("app.services.mqtt_subscriber.ingest", new=AsyncMock()) as ing,
    ):
        await sub._process_message("spy/one", b"42")
        ing.assert_awaited_once()
        assert ing.await_args.args[0] is spy


@pytest.mark.asyncio
async def test_an_unowned_topic_is_ignored_without_raising(db_session):
    sub = MQTTSubscriber()
    sub._subscribed = {}
    with (
        _session_factory(db_session),
        patch("app.services.mqtt_subscriber.ingest", new=AsyncMock()) as ing,
    ):
        await sub._process_message("nobody/cares", b"42")
        ing.assert_not_called()


@pytest.mark.asyncio
async def test_reload_subscribes_new_topics_and_unsubscribes_dropped_ones():
    sub = MQTTSubscriber()
    client = AsyncMock()
    sub._client = client
    sub._subscribed = {"old/topic": _Spy()}
    sub._confirmed = {"old/topic"}
    with patch.object(
        MQTTSubscriber, "_desired_subscriptions", new=AsyncMock(return_value={"new/topic": _Spy()})
    ):
        await sub.reload()
    client.subscribe.assert_awaited_once_with("new/topic")
    client.unsubscribe.assert_awaited_once_with("old/topic")
    assert set(sub._subscribed) == {"new/topic"}


@pytest.mark.asyncio
async def test_the_new_map_is_installed_before_subscribing(db_session):
    """R1-H3: retained messages arrive the instant SUBSCRIBE lands."""
    sub = MQTTSubscriber()
    spy = _Spy()
    seen_during_subscribe: list[bool] = []

    client = AsyncMock()

    async def _subscribe(topic):
        seen_during_subscribe.append("new/topic" in sub._subscribed)

    client.subscribe.side_effect = _subscribe
    sub._client = client
    sub._subscribed = {}
    with patch.object(
        MQTTSubscriber, "_desired_subscriptions", new=AsyncMock(return_value={"new/topic": spy})
    ):
        await sub.reload()
    assert seen_during_subscribe == [True], "map must be live before SUBSCRIBE"


@pytest.mark.asyncio
async def test_reload_is_a_no_op_when_disconnected():
    sub = MQTTSubscriber()
    sub._client = None
    await sub.reload()  # must not raise


@pytest.mark.asyncio
async def test_a_failed_subscribe_is_retried_on_the_next_reload():
    """R1-H3 round 2: a failed SUBSCRIBE must not look permanently done.

    The dispatch map is the union, so diffing against it would mark a failed
    topic as already subscribed. The mapping would then look healthy in the UI
    and receive nothing, forever.
    """
    sub = MQTTSubscriber()
    spy = _Spy()
    client = AsyncMock()
    client.subscribe.side_effect = [RuntimeError("broker said no"), None]
    sub._client = client
    with patch.object(
        MQTTSubscriber, "_desired_subscriptions", new=AsyncMock(return_value={"flaky/t": spy})
    ):
        await sub.reload()
        assert "flaky/t" not in sub._confirmed
        await sub.reload()
    assert "flaky/t" in sub._confirmed
    assert client.subscribe.await_count == 2


@pytest.mark.asyncio
async def test_a_reconnect_resubscribes_everything():
    """A fresh client holds no subscriptions, so _confirmed must be cleared.

    Deliberately exercises `_reset_subscription_state()` and then `reload()`,
    rather than asserting an assignment the test made itself. Delete the body of
    `_reset_subscription_state` and this fails: reload would diff against stale
    confirmations and re-subscribe nothing on a reconnected client.
    """
    sub = MQTTSubscriber()
    spy = _Spy()
    client = AsyncMock()
    sub._client = client
    sub._confirmed = {"spy/one"}  # what the PREVIOUS connection had ACKed
    sub._subscribed = {"spy/one": spy}

    sub._reset_subscription_state()  # what _run does on connect

    with patch.object(
        MQTTSubscriber, "_desired_subscriptions", new=AsyncMock(return_value={"spy/one": spy})
    ):
        await sub.reload()

    client.subscribe.assert_awaited_once_with("spy/one")
    assert sub._confirmed == {"spy/one"}


@pytest.mark.asyncio
async def test_reload_leaves_unchanged_topics_alone():
    sub = MQTTSubscriber()
    client = AsyncMock()
    sub._client = client
    keep = _Spy()
    sub._subscribed = {"keep/me": keep}
    sub._confirmed = {"keep/me"}  # already ACKed by the broker
    with patch.object(
        MQTTSubscriber, "_desired_subscriptions", new=AsyncMock(return_value={"keep/me": keep})
    ):
        await sub.reload()
    client.subscribe.assert_not_called()
    client.unsubscribe.assert_not_called()


@pytest.mark.asyncio
async def test_the_retain_flag_reaches_the_envelope(db_session):
    """R1: ingest can only drop a replay it can see."""
    sub = MQTTSubscriber()
    spy = _Spy()
    sub._subscribed = {"spy/one": spy}
    with (
        _session_factory(db_session),
        patch("app.services.mqtt_subscriber.ingest", new=AsyncMock()) as ing,
    ):
        await sub._process_message("spy/one", b"42", retain=True)
        await sub._process_message("spy/one", b"43", retain=False)
    assert [call.args[1].retain for call in ing.await_args_list] == [True, False]


@pytest.mark.asyncio
async def test_the_message_loop_passes_the_brokers_retain_flag():
    """`_run` is where aiomqtt's `Message.retain` is read; drop it there and
    every replay looks live again."""

    class _Message:
        def __init__(self, retain: bool) -> None:
            self.topic = "spy/one"
            self.payload = b"1"
            self.retain = retain

    class _Client:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc) -> bool:
            return False

        async def subscribe(self, _topic) -> None:
            return None

        @property
        def messages(self):
            async def _gen():
                yield _Message(True)
                yield _Message(False)

            return _gen()

    sub = MQTTSubscriber()
    sub._running = True
    seen: list[bool | None] = []

    # Tolerates the old two-argument call, so the red run fails on the
    # assertion instead of looping on the reconnect sleep.
    async def _process(topic, payload, retain=None):
        seen.append(retain)
        if len(seen) == 2:
            sub._running = False

    config = {
        "host": "h",
        "port": 1883,
        "username": None,
        "password": None,
        "topic_prefix": "wican",
        "use_tls": False,
    }
    with (
        patch("aiomqtt.Client", _Client),
        patch.object(MQTTSubscriber, "_get_config", new=AsyncMock(return_value=config)),
        patch.object(MQTTSubscriber, "_desired_subscriptions", new=AsyncMock(return_value={})),
        patch.object(sub, "_process_message", new=_process),
    ):
        await sub._run()
    assert seen == [True, False]


# ---------------------------------------------------------------------------
# A-14: the connect-time subscribe behaves like reload()
# ---------------------------------------------------------------------------


class _Reconnected(BaseException):
    """Raised by a second `_get_config` call: the loop went round again.

    A BaseException, so `_run`'s own `except Exception` can't swallow it.
    """


_CONFIG = {
    "host": "h",
    "port": 1883,
    "username": None,
    "password": None,
    "topic_prefix": "wican",
    "use_tls": False,
}


def _one_connection_config(sub: MQTTSubscriber) -> AsyncMock:
    calls = 0

    async def _config():
        nonlocal calls
        calls += 1
        if calls > 1:
            raise _Reconnected
        return _CONFIG

    sub._reconnect_delay = 0
    return AsyncMock(side_effect=_config)


def _client_class(fail: set[str], subscribed: list[str], gate: asyncio.Event | None = None):
    class _Message:
        topic = "good/t"
        payload = b"1"
        retain = False

    class _Client:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc) -> bool:
            return False

        async def subscribe(self, topic) -> None:
            subscribed.append(topic)
            if topic in fail:
                raise RuntimeError("broker said no")

        @property
        def messages(self):
            async def _gen():
                if gate is not None:
                    await gate.wait()
                yield _Message()

            return _gen()

    return _Client


@pytest.mark.asyncio
async def test_a_subscribe_failure_at_connect_keeps_the_connection():
    """One refused topic used to raise out of the connect block: the whole
    connection dropped, every other topic with it, and it reconnected into the
    same failure forever."""
    sub = MQTTSubscriber()
    sub._running = True
    spy = _Spy()
    processed: list[str] = []
    subscribed: list[str] = []

    async def _process(topic, payload, retain=False):
        processed.append(topic)
        sub._running = False

    with (
        patch("aiomqtt.Client", _client_class({"bad/t"}, subscribed)),
        patch.object(MQTTSubscriber, "_get_config", new=_one_connection_config(sub)),
        patch.object(
            MQTTSubscriber,
            "_desired_subscriptions",
            new=AsyncMock(return_value={"bad/t": spy, "good/t": spy}),
        ),
        patch.object(sub, "_process_message", new=_process),
    ):
        await asyncio.wait_for(sub._run(), timeout=5)

    assert processed == ["good/t"]
    assert sorted(subscribed) == ["bad/t", "good/t"]
    # Left out, so the next reload() retries it.
    assert sub._confirmed == {"good/t"}
    assert set(sub._subscribed) == {"bad/t", "good/t"}


@pytest.mark.asyncio
async def test_the_connect_time_subscribe_waits_for_a_reload_in_progress():
    """It ran outside `_reload_lock`, so a topic-map save landing during a
    reconnect could interleave its subscribe/unsubscribe with this one."""
    sub = MQTTSubscriber()
    sub._running = True
    spy = _Spy()
    subscribed: list[str] = []
    gate = asyncio.Event()

    async def _process(topic, payload, retain=False):
        sub._running = False

    with (
        patch("aiomqtt.Client", _client_class(set(), subscribed, gate)),
        patch.object(MQTTSubscriber, "_get_config", new=_one_connection_config(sub)),
        patch.object(
            MQTTSubscriber, "_desired_subscriptions", new=AsyncMock(return_value={"good/t": spy})
        ),
        patch.object(sub, "_process_message", new=_process),
    ):
        await sub._reload_lock.acquire()
        run = asyncio.create_task(sub._run())
        for _ in range(20):
            await asyncio.sleep(0)
        held_back = list(subscribed)
        sub._reload_lock.release()
        gate.set()
        await asyncio.wait_for(run, timeout=5)

    assert held_back == []
    assert subscribed == ["good/t"]
    assert sub._confirmed == {"good/t"}

"""MQTT subscriber service for WiCAN device telemetry.

This service provides an alternative to HTTPS POST ingestion by subscribing
to WiCAN MQTT topics on a local broker. It integrates with existing telemetry
storage, session management, and device discovery.
"""

import asyncio
import logging
import ssl
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.services.livelink_ingest import ingest
from app.services.livelink_sources.base import BaseSourceModule, MqttEnvelope
from app.services.livelink_sources.registry import default_registry
from app.services.settings_service import SecretUnreadableError, SettingsService, reenter_message
from app.utils.datetime_utils import utc_now
from app.utils.household_time import load_household_zone
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


MAX_DISCOVERY_SECONDS = 60
MAX_DISCOVERY_TOPICS = 500
MAX_DISCOVERY_SAMPLE = 256


class MqttNotConfiguredError(Exception):
    """MQTT is off, or on with nothing it can connect with. The message says which."""


class _DiscoveryCollector:
    """Accumulates distinct topics with one truncated sample each."""

    def __init__(self, max_topics: int, max_sample: int) -> None:
        self._max_topics = max_topics
        self._max_sample = max_sample
        self._seen: dict[str, str] = {}

    def observe(self, topic: str, payload: bytes) -> None:
        """Record a topic, keeping the FIRST sample seen for it.

        Truncates BYTES before decoding. Slicing after decode bounds
        characters, not bytes, so the stated 256-byte limit would not hold for
        multi-byte UTF-8 and the whole payload gets allocated regardless.
        """
        if topic in self._seen or len(self._seen) >= self._max_topics:
            return
        self._seen[topic] = payload[: self._max_sample].decode("utf-8", errors="replace")

    def full(self) -> bool:
        """Whether the topic cap has been reached."""
        return len(self._seen) >= self._max_topics

    def results(self) -> list[dict[str, str]]:
        """Observed topics, in first-seen order."""
        return [{"topic": t, "sample": s} for t, s in self._seen.items()]


class MQTTSubscriber:
    """MQTT subscriber for WiCAN device telemetry.

    Subscribes to WiCAN MQTT topics and routes messages to existing
    telemetry processing services.

    Topic structure:
    - {prefix}/{device_id}/can/status - ECU online/offline status
    - {prefix}/{device_id}/battery - Battery voltage
    - {prefix}/{device_id}/can/rx - Telemetry data (odometer, temps, etc.)
    """

    def __init__(self) -> None:
        """Initialize MQTT subscriber."""
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._client: Any | None = None  # aiomqtt.Client when connected
        self._topic_prefix: str = "wican"
        self._reconnect_delay = 5  # seconds
        self._max_reconnect_delay = 60  # seconds
        self._connection_status = "disconnected"
        self._last_message_at: datetime | None = None
        self._messages_processed = 0

        self._subscribed: dict[str, BaseSourceModule] = {}
        #: Serializes reload(). Every topic-map mutation calls it, and FastAPI
        #: serves requests concurrently, so two admin saves can otherwise
        #: interleave subscribe/unsubscribe and leave the map disagreeing with
        #: the broker.
        self._reload_lock = asyncio.Lock()
        #: Topics the broker has ACKed. Distinct from `_subscribed`, which is
        #: the dispatch map and is deliberately a superset during a reload.
        #: Reset on every reconnect: a new client has no subscriptions.
        self._confirmed: set[str] = set()
        self._discovering = False

    async def start(self) -> None:
        """Start the MQTT subscriber background task."""
        if self._running:
            logger.warning("MQTT subscriber already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("MQTT subscriber started")

    async def stop(self) -> None:
        """Stop the MQTT subscriber."""
        self._running = False
        self._client = None
        self._connection_status = "disconnected"

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("MQTT subscriber stopped")

    @property
    def is_running(self) -> bool:
        """Check if subscriber is running."""
        return self._running and self._task is not None

    @property
    def status(self) -> dict[str, Any]:
        """Get subscriber status."""
        return {
            "running": self._running,
            "connection_status": self._connection_status,
            "last_message_at": self._last_message_at.isoformat() if self._last_message_at else None,
            "messages_processed": self._messages_processed,
        }

    @property
    def is_connected(self) -> bool:
        """Check if MQTT client is connected."""
        return self._client is not None and self._connection_status == "connected"

    async def publish(self, topic: str, payload: str) -> None:
        """Publish a message to an MQTT topic.

        Args:
            topic: MQTT topic to publish to.
            payload: JSON string payload.

        Raises:
            RuntimeError: If MQTT client is not connected.
        """
        if self._client is None:
            raise RuntimeError("MQTT client is not connected")

        await self._client.publish(topic, payload.encode("utf-8"))
        logger.debug("Published MQTT message to %s", topic)

    async def send_device_command(self, device_id: str, command: str) -> None:
        """Send a command to a WiCAN device via MQTT.

        Args:
            device_id: Target device ID (12-char hex).
            command: Command JSON string (e.g., '{"get_vbatt":""}').

        Raises:
            RuntimeError: If MQTT client is not connected.
        """
        topic = f"{self._topic_prefix}/{device_id}/cmd"
        await self.publish(topic, command)
        logger.info("Sent command to device %s: %s", sanitize_for_log(device_id), command)

    async def _get_config(self) -> dict[str, Any] | None:
        """Get MQTT configuration from settings, or None when it can't connect."""
        try:
            return await self._load_config()
        except MqttNotConfiguredError:
            return None

    async def _load_config(self) -> dict[str, Any]:
        """MQTT configuration from settings.

        Raises MqttNotConfiguredError saying why when there's nothing to
        connect with, so topic discovery can tell the operator instead of
        reporting an empty broker (B-4).
        """
        async with AsyncSessionLocal() as db:
            await load_household_zone(db)
            if not await SettingsService.get_bool(db, "livelink_mqtt_enabled", default=False):
                raise MqttNotConfiguredError("MQTT is off; turn it on in the Mosquitto settings")

            broker_host = await SettingsService.get(db, "livelink_mqtt_broker_host")
            if not broker_host or not broker_host.value:
                logger.error("MQTT enabled but no broker host configured")
                raise MqttNotConfiguredError("MQTT is on but no broker host is configured")

            broker_port = await SettingsService.get(db, "livelink_mqtt_broker_port")
            username = await SettingsService.get(db, "livelink_mqtt_username")
            try:
                # Optional: no password connects anonymously, so an unreadable one
                # must stop here rather than read as unset (R1-M1).
                password = await SettingsService.get_secret(db, "livelink_mqtt_password")
            except SecretUnreadableError as e:
                logger.error(
                    "MQTT enabled but the stored %s can't be decrypted; re-enter it in Settings",
                    e.key,
                )
                raise MqttNotConfiguredError(reenter_message("MQTT password")) from e
            topic_prefix = await SettingsService.get(db, "livelink_mqtt_topic_prefix")
            use_tls = await SettingsService.get_bool(db, "livelink_mqtt_use_tls", default=False)

            return {
                "host": broker_host.value,
                "port": int(broker_port.value) if broker_port and broker_port.value else 1883,
                "username": username.value if username and username.value else None,
                "password": password or None,
                "topic_prefix": topic_prefix.value
                if topic_prefix and topic_prefix.value
                else "wican",
                "use_tls": use_tls,
            }

    async def configured_topic_prefix(self, db: AsyncSession) -> str | None:
        """The configured WiCAN topic prefix, or None when MQTT is off.

        Reads through the CALLER's session rather than delegating to
        `_get_config`, which opens its own `AsyncSessionLocal`. That would
        reach the configured database rather than the one the caller is using,
        which under test is a different file entirely.

        Mirrors the two keys `_get_config` consults for this, including its
        "wican" default.
        """
        if not await SettingsService.get_bool(db, "livelink_mqtt_enabled", default=False):
            return None
        prefix = await SettingsService.get(db, "livelink_mqtt_topic_prefix")
        return prefix.value if prefix and prefix.value else "wican"

    async def _desired_subscriptions(self) -> dict[str, BaseSourceModule]:
        """Topic to owning module, from the registry, using a fresh session."""
        async with AsyncSessionLocal() as db:
            return await default_registry().mqtt_subscriptions(db)

    def _reset_subscription_state(self) -> None:
        """Forget which topics the broker had ACKed.

        Called on every (re)connect. A new client holds no subscriptions, so
        leaving `_confirmed` populated would make `reload()` diff against a
        previous connection's state and re-subscribe nothing.
        """
        self._confirmed = set()

    async def reload(self) -> None:
        """Re-read subscriptions and apply the delta to the live connection.

        Called whenever a topic-map row changes. Without it, a mapping added
        from the UI does nothing until the container restarts, which would be
        the most confusing possible failure mode for that feature.

        aiomqtt permits subscribe/unsubscribe from another task while the
        message loop is running, so this needs no reconnect.
        """
        if self._client is None:
            return
        async with self._reload_lock:
            desired = await self._desired_subscriptions()

            # Install the new dispatch map BEFORE subscribing. The broker can
            # deliver a retained message the instant SUBSCRIBE lands, and with
            # the old map `resolve_topic` would return None and drop it. That
            # still matters for a retained LWT `offline`, which ingest applies;
            # retained telemetry and a retained `online` are ignored there by
            # design (R1).
            #
            # Publishing the union first is safe in the other direction: a
            # topic that is in the map but not yet subscribed simply never
            # arrives.
            self._subscribed = {**self._subscribed, **desired}

            # The retry set is desired MINUS CONFIRMED, never desired minus the
            # dispatch map. The map is the union installed above, so diffing
            # against it would treat a topic whose SUBSCRIBE failed as already
            # subscribed and never retry it: the mapping would sit in the UI
            # looking healthy and silently receive nothing, forever.
            for topic in sorted(set(desired) - self._confirmed):
                try:
                    await self._client.subscribe(topic)
                except Exception as exc:
                    logger.error(
                        "SUBSCRIBE failed for %s: %s (will retry on next reload)",
                        sanitize_for_log(topic),
                        exc,
                    )
                    continue  # deliberately NOT added to _confirmed
                self._confirmed.add(topic)
                logger.info("Subscribed to MQTT topic: %s", sanitize_for_log(topic))

            for topic in sorted(self._confirmed - set(desired)):
                try:
                    await self._client.unsubscribe(topic)
                except Exception as exc:
                    logger.error("UNSUBSCRIBE failed for %s: %s", sanitize_for_log(topic), exc)
                self._confirmed.discard(topic)
                logger.info("Unsubscribed from MQTT topic: %s", sanitize_for_log(topic))

            # Only now drop departed topics from the dispatch map.
            self._subscribed = desired

    async def discover_topics(self, prefix: str, seconds: int = 15) -> list[dict[str, str]]:
        """Listen on a temporary client and report what is publishing.

        Opens its OWN client so the live subscription set is untouched. Bounded
        on every axis: duration, distinct topics and sample size. Raises
        RuntimeError if a run is already in progress, MqttNotConfiguredError
        when MQTT can't connect as configured, and lets aiomqtt's MqttError out
        when the broker refuses or can't be reached.
        """
        import aiomqtt

        # Claim the guard BEFORE the first await. Checking here and setting it
        # after `_get_config()` leaves a window in which two concurrent
        # requests both pass.
        if self._discovering:
            raise RuntimeError("A discovery run is already in progress")
        self._discovering = True
        try:
            config = await self._load_config()

            seconds = max(1, min(seconds, MAX_DISCOVERY_SECONDS))
            collector = _DiscoveryCollector(MAX_DISCOVERY_TOPICS, MAX_DISCOVERY_SAMPLE)
            async with aiomqtt.Client(
                hostname=config["host"],
                port=config["port"],
                username=config["username"],
                password=config["password"],
                tls_context=ssl.create_default_context() if config["use_tls"] else None,
            ) as client:
                await client.subscribe(prefix)

                async def _collect() -> None:
                    async for message in client.messages:
                        collector.observe(str(message.topic), message.payload)
                        if collector.full():
                            return

                try:
                    await asyncio.wait_for(_collect(), timeout=seconds)
                except TimeoutError:
                    pass
        finally:
            self._discovering = False
        return collector.results()

    async def _run(self) -> None:
        """Main subscriber loop with reconnection handling."""
        # Import here to avoid startup issues if aiomqtt not installed
        try:
            import aiomqtt
        except ImportError:
            logger.error("aiomqtt not installed - MQTT support unavailable")
            self._connection_status = "error"
            self._running = False
            return

        reconnect_delay = self._reconnect_delay

        while self._running:
            try:
                config = await self._get_config()
                if not config:
                    self._connection_status = "disabled"
                    logger.info("MQTT not configured or disabled, waiting...")
                    await asyncio.sleep(30)
                    continue

                logger.info(
                    "Connecting to MQTT broker %s:%d",
                    config["host"],
                    config["port"],
                )
                self._connection_status = "connecting"

                # Build TLS context if needed
                tls_context = None
                if config["use_tls"]:
                    tls_context = ssl.create_default_context()

                async with aiomqtt.Client(
                    hostname=config["host"],
                    port=config["port"],
                    username=config["username"],
                    password=config["password"],
                    tls_context=tls_context,
                ) as client:
                    self._client = client
                    self._topic_prefix = config["topic_prefix"]
                    reconnect_delay = self._reconnect_delay  # Reset on successful connect
                    self._connection_status = "connected"

                    # Under the reload lock, so a topic-map save landing mid-connect
                    # can't interleave with this (A-14). A fresh client holds no
                    # subscriptions, so forget what the previous connection had
                    # ACKed or reload() would skip everything after a reconnect.
                    async with self._reload_lock:
                        self._reset_subscription_state()
                        self._subscribed = await self._desired_subscriptions()
                        for topic in sorted(self._subscribed):
                            # Per topic, like reload(): one refused topic used to drop
                            # the whole connection and reconnect into the same refusal.
                            try:
                                await client.subscribe(topic)
                            except Exception as exc:
                                logger.error(
                                    "SUBSCRIBE failed for %s: %s (will retry on next reload)",
                                    sanitize_for_log(topic),
                                    exc,
                                )
                                continue  # left out of _confirmed, so reload() retries it
                            self._confirmed.add(topic)
                            logger.info("Subscribed to MQTT topic: %s", sanitize_for_log(topic))

                    # Process messages
                    async for message in client.messages:
                        if not self._running:
                            break
                        try:
                            await self._process_message(
                                str(message.topic), message.payload, retain=bool(message.retain)
                            )
                        except Exception as e:
                            logger.error("Error processing MQTT message: %s", e)

            except asyncio.CancelledError:
                self._client = None
                raise
            except Exception as e:
                self._client = None
                logger.error("MQTT connection error: %s", e)
                self._connection_status = "error"

            if self._running:
                logger.info("Reconnecting to MQTT in %d seconds...", reconnect_delay)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, self._max_reconnect_delay)

    async def _process_message(self, topic: str, payload: bytes, retain: bool = False) -> None:
        """Dispatch one message to its module and run the pipeline.

        `retain` is the broker's flag, passed through so ingest can tell a
        replay from something the device just said.
        """
        module = default_registry().resolve_topic(topic, self._subscribed)
        if module is None:
            logger.debug("No module owns topic: %s", sanitize_for_log(topic))
            return

        async with AsyncSessionLocal() as db:
            await load_household_zone(db)
            try:
                await ingest(module, MqttEnvelope(topic=topic, payload=payload, retain=retain), db)
                await db.commit()
                self._messages_processed += 1
                self._last_message_at = utc_now()
            except Exception as e:
                await db.rollback()
                logger.error("Error handling MQTT message: %s", e, exc_info=True)
                raise


# Singleton instance
mqtt_subscriber = MQTTSubscriber()

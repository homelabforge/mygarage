"""MQTT subscriber service for WiCAN device telemetry.

This service provides an alternative to HTTPS POST ingestion by subscribing
to WiCAN MQTT topics on a local broker. It integrates with existing telemetry
storage, session management, and device discovery.
"""

import asyncio
import json
import logging
import ssl
from datetime import UTC, datetime
from typing import Any

from app.database import AsyncSessionLocal
from app.services.livelink_service import LiveLinkService
from app.services.session_service import SessionService
from app.services.settings_service import SettingsService
from app.services.telemetry_service import TelemetryService
from app.utils.autopid_normalizer import normalize_autopid_data

logger = logging.getLogger(__name__)


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
        logger.info("Sent command to device %s: %s", device_id, command)

    async def _get_config(self) -> dict[str, Any] | None:
        """Get MQTT configuration from settings."""
        async with AsyncSessionLocal() as db:
            enabled = await SettingsService.get(db, "livelink_mqtt_enabled")
            if not enabled or enabled.value != "true":
                return None

            broker_host = await SettingsService.get(db, "livelink_mqtt_broker_host")
            if not broker_host or not broker_host.value:
                logger.error("MQTT enabled but no broker host configured")
                return None

            broker_port = await SettingsService.get(db, "livelink_mqtt_broker_port")
            username = await SettingsService.get(db, "livelink_mqtt_username")
            password = await SettingsService.get(db, "livelink_mqtt_password")
            topic_prefix = await SettingsService.get(db, "livelink_mqtt_topic_prefix")
            use_tls = await SettingsService.get(db, "livelink_mqtt_use_tls")

            return {
                "host": broker_host.value,
                "port": int(broker_port.value) if broker_port and broker_port.value else 1883,
                "username": username.value if username and username.value else None,
                "password": password.value if password and password.value else None,
                "topic_prefix": topic_prefix.value
                if topic_prefix and topic_prefix.value
                else "wican",
                "use_tls": use_tls and use_tls.value == "true",
            }

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

                    # Subscribe to all WiCAN topics
                    # Pattern: wican/+/# matches wican/<device_id>/<subtopic>
                    topic_pattern = f"{config['topic_prefix']}/+/#"
                    await client.subscribe(topic_pattern)
                    logger.info("Subscribed to MQTT topic: %s", topic_pattern)

                    # Process messages
                    async for message in client.messages:
                        if not self._running:
                            break
                        try:
                            await self._process_message(
                                str(message.topic),
                                message.payload,
                                config["topic_prefix"],
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

    async def _process_message(
        self,
        topic: str,
        payload: bytes,
        topic_prefix: str,
    ) -> None:
        """Process an incoming MQTT message.

        Topic structure:
        - {prefix}/{device_id}/can/status - Device online/offline
        - {prefix}/{device_id}/battery - Battery voltage
        - {prefix}/{device_id}/can/rx - Telemetry data
        """
        # Parse topic to extract device_id and message type
        parts = topic.split("/")
        if len(parts) < 3:
            logger.debug("Ignoring malformed topic: %s", topic)
            return

        # Expected: prefix/device_id/...
        if parts[0] != topic_prefix:
            return

        device_id = parts[1].lower().replace(":", "").replace("-", "")
        subtopic = "/".join(parts[2:])

        # Parse payload
        try:
            data = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.debug("Failed to parse MQTT payload: %s", e)
            return

        logger.debug(
            "MQTT message: device=%s, subtopic=%s, data=%s",
            device_id,
            subtopic,
            data,
        )

        # Route to appropriate handler
        async with AsyncSessionLocal() as db:
            try:
                if subtopic == "can/status":
                    await self._handle_status(db, device_id, data)
                elif subtopic == "battery":
                    await self._handle_battery(db, device_id, data)
                elif subtopic == "can/rx":
                    await self._handle_telemetry(db, device_id, data)
                else:
                    logger.debug("Ignoring unknown subtopic: %s", subtopic)
                    return

                await db.commit()
                self._messages_processed += 1
                self._last_message_at = datetime.now(UTC)

            except Exception as e:
                await db.rollback()
                logger.error("Error handling MQTT message: %s", e, exc_info=True)
                raise

    async def _handle_status(
        self,
        db: Any,
        device_id: str,
        data: dict[str, Any],
    ) -> None:
        """Handle device status message (ECU online/offline)."""
        status = data.get("status", "unknown").lower()
        livelink_service = LiveLinkService(db)

        # Auto-discover device if needed
        device, is_new = await livelink_service.auto_discover_device(device_id)

        if is_new:
            logger.info("Auto-discovered new device via MQTT: %s", device_id)

        # Map status to ecu_status — only explicit values, not coerced
        if status == "online":
            ecu_status = "online"
        elif status == "offline":
            ecu_status = "offline"
        else:
            ecu_status = "unknown"

        # Handle session transitions with grace period for WiFi drop resilience.
        # Skip transitions for unknown status — only explicit online/offline matters.
        if device.vin and ecu_status != "unknown":
            grace_seconds = await livelink_service.get_session_grace_period_seconds()
            if ecu_status == "online":
                # ECU came online — if pending offline, WiFi recovered (clear pending)
                if device.pending_offline_at:
                    await livelink_service.clear_pending_offline(device_id)
                    logger.debug("Cleared pending offline for %s (WiFi recovered)", device_id)
                else:
                    # Not pending — genuine ECU online, start session
                    session_service = SessionService(db)
                    await session_service.handle_ecu_online(device.vin, device_id)
            else:
                # ECU offline — start grace period instead of immediate session end
                if grace_seconds > 0:
                    await livelink_service.set_pending_offline(device_id)
                    logger.debug(
                        "Set pending offline for %s (grace period: %ds)",
                        device_id,
                        grace_seconds,
                    )
                else:
                    # Grace period disabled — immediate session end
                    session_service = SessionService(db)
                    await session_service.handle_ecu_offline(device.vin, device_id)

        # Update device status (after session detection has read old state)
        await livelink_service.update_device_status(
            device_id=device_id,
            device_status="online",  # Device is online if we're getting MQTT messages
            ecu_status=ecu_status,
        )

        logger.debug("Updated device %s status: ecu=%s", device_id, ecu_status)

    async def _handle_battery(
        self,
        db: Any,
        device_id: str,
        data: dict[str, Any],
    ) -> None:
        """Handle battery voltage message."""
        battery_voltage = data.get("battery_voltage")
        if battery_voltage is None:
            return

        livelink_service = LiveLinkService(db)

        # Ensure device exists
        device = await livelink_service.get_device_by_id(device_id)
        if not device:
            device, _ = await livelink_service.auto_discover_device(device_id)

        # Update battery voltage
        await livelink_service.update_device_status(
            device_id=device_id,
            battery_voltage=float(battery_voltage),
            device_status="online",
        )

        # If device is linked, also store as telemetry
        if device.vin:
            telemetry_service = TelemetryService(db)
            await telemetry_service.store_telemetry(
                vin=device.vin,
                device_id=device_id,
                autopid_data={"BATTERY_VOLTAGE": float(battery_voltage)},
                config={"BATTERY_VOLTAGE": {"unit": "V", "class": "voltage"}},
                timestamp=datetime.now(UTC),
            )

    async def _handle_telemetry(
        self,
        db: Any,
        device_id: str,
        data: dict[str, Any],
    ) -> None:
        """Handle telemetry data message (odometer, temps, etc.)."""
        livelink_service = LiveLinkService(db)

        # Get device
        device = await livelink_service.get_device_by_id(device_id)
        if not device:
            # Auto-discover but don't process telemetry until linked
            device, _ = await livelink_service.auto_discover_device(device_id)
            logger.debug("Device %s not linked, skipping telemetry", device_id)
            return

        if not device.vin:
            logger.debug("Device %s not linked to vehicle, skipping telemetry", device_id)
            return

        if not device.enabled:
            return

        # If device has a pending offline, receiving telemetry means WiFi recovered
        if device.pending_offline_at:
            await livelink_service.clear_pending_offline(device_id)
            logger.debug("Cleared pending offline for %s (telemetry received)", device_id)

        # Infer ECU status from telemetry: if we're receiving data, ECU must be on
        # This handles WiCAN devices that don't send explicit can/status messages
        ecu_was_offline = device.ecu_status != "online"

        # If ECU just came online, start a drive session BEFORE updating status,
        # so the transition detector sees the old ecu_status
        if ecu_was_offline:
            session_service = SessionService(db)
            await session_service.handle_ecu_online(device.vin, device_id)
            logger.info(
                "ECU online inferred from telemetry for device %s, started session",
                device_id,
            )

        # Update last_seen and ECU status (after session detection)
        await livelink_service.update_device_status(
            device_id=device_id,
            device_status="online",
            ecu_status="online",
        )

        # Normalize parameter keys and filter values via normalizer
        normalized = normalize_autopid_data(data)
        # Uppercase keys with spaces replaced by underscores (MQTT convention)
        autopid_data: dict[str, float | int | str | None] = {
            k.upper().replace(" ", "_"): v for k, v in normalized.items()
        }

        if not autopid_data:
            return

        # Store telemetry using existing service (includes validation)
        telemetry_service = TelemetryService(db)
        store_result = await telemetry_service.store_telemetry(
            vin=device.vin,
            device_id=device_id,
            autopid_data=autopid_data,
            config={},  # No config metadata from MQTT
            timestamp=datetime.now(UTC),
        )

        # Check thresholds on validated data only (not rejected garbage)
        for param_key, value in store_result.validated_data.items():
            if value is not None and isinstance(value, (int, float)):
                await telemetry_service.check_thresholds(
                    vin=device.vin,
                    param_key=param_key,
                    value=float(value),
                )

        logger.debug(
            "Stored %d telemetry parameters for device %s",
            store_result.stored_count,
            device_id,
        )


# Singleton instance
mqtt_subscriber = MQTTSubscriber()

"""Unit tests for device command service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_device(
    device_id: str = "aabbccddeeff",
    device_status: str = "online",
    ecu_status: str = "online",
):
    """Create a mock LiveLinkDevice."""
    device = MagicMock()
    device.device_id = device_id
    device.device_status = device_status
    device.ecu_status = ecu_status
    return device


class TestSendCommand:
    """Test send_command function."""

    @pytest.mark.asyncio
    async def test_valid_get_vbatt(self):
        """get_vbatt command should publish to MQTT."""
        from app.services.device_command_service import send_command

        db = AsyncMock()
        device = _mock_device()

        mock_livelink = AsyncMock()
        mock_livelink.get_device_by_id = AsyncMock(return_value=device)

        mock_subscriber = MagicMock()
        mock_subscriber.is_connected = True
        mock_subscriber.send_device_command = AsyncMock()

        with (
            patch(
                "app.services.device_command_service.LiveLinkService", return_value=mock_livelink
            ),
            patch("app.services.mqtt_subscriber.mqtt_subscriber", mock_subscriber),
        ):
            result = await send_command(db, "aabbccddeeff", "get_vbatt")

        assert result["status"] == "sent"
        mock_subscriber.send_device_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_valid_get_autopid_data(self):
        """get_autopid_data command should work when ECU is online."""
        from app.services.device_command_service import send_command

        db = AsyncMock()
        device = _mock_device(ecu_status="online")

        mock_livelink = AsyncMock()
        mock_livelink.get_device_by_id = AsyncMock(return_value=device)

        mock_subscriber = MagicMock()
        mock_subscriber.is_connected = True
        mock_subscriber.send_device_command = AsyncMock()

        with (
            patch(
                "app.services.device_command_service.LiveLinkService", return_value=mock_livelink
            ),
            patch("app.services.mqtt_subscriber.mqtt_subscriber", mock_subscriber),
        ):
            result = await send_command(db, "aabbccddeeff", "get_autopid_data")

        assert result["status"] == "sent"

    @pytest.mark.asyncio
    async def test_unknown_command(self):
        """Unknown command should raise ValueError."""
        from app.services.device_command_service import send_command

        db = AsyncMock()

        with pytest.raises(ValueError, match="Unknown command"):
            await send_command(db, "aabbccddeeff", "launch_missiles")

    @pytest.mark.asyncio
    async def test_device_not_found(self):
        """Missing device should raise ValueError."""
        from app.services.device_command_service import send_command

        db = AsyncMock()

        mock_livelink = AsyncMock()
        mock_livelink.get_device_by_id = AsyncMock(return_value=None)

        with (
            patch(
                "app.services.device_command_service.LiveLinkService", return_value=mock_livelink
            ),
            pytest.raises(ValueError, match="not found"),
        ):
            await send_command(db, "aabbccddeeff", "get_vbatt")

    @pytest.mark.asyncio
    async def test_device_offline(self):
        """Offline device should raise ValueError."""
        from app.services.device_command_service import send_command

        db = AsyncMock()
        device = _mock_device(device_status="offline")

        mock_livelink = AsyncMock()
        mock_livelink.get_device_by_id = AsyncMock(return_value=device)

        with (
            patch(
                "app.services.device_command_service.LiveLinkService", return_value=mock_livelink
            ),
            pytest.raises(ValueError, match="must be online"),
        ):
            await send_command(db, "aabbccddeeff", "get_vbatt")

    @pytest.mark.asyncio
    async def test_ecu_required_but_offline(self):
        """get_autopid_data with ECU offline should raise ValueError."""
        from app.services.device_command_service import send_command

        db = AsyncMock()
        device = _mock_device(ecu_status="offline")

        mock_livelink = AsyncMock()
        mock_livelink.get_device_by_id = AsyncMock(return_value=device)

        with (
            patch(
                "app.services.device_command_service.LiveLinkService", return_value=mock_livelink
            ),
            pytest.raises(ValueError, match="requires ECU"),
        ):
            await send_command(db, "aabbccddeeff", "get_autopid_data")

    @pytest.mark.asyncio
    async def test_mqtt_not_connected(self):
        """MQTT not connected should raise RuntimeError."""
        from app.services.device_command_service import send_command

        db = AsyncMock()
        device = _mock_device()

        mock_livelink = AsyncMock()
        mock_livelink.get_device_by_id = AsyncMock(return_value=device)

        mock_subscriber = MagicMock()
        mock_subscriber.is_connected = False

        with (
            patch(
                "app.services.device_command_service.LiveLinkService", return_value=mock_livelink
            ),
            patch("app.services.mqtt_subscriber.mqtt_subscriber", mock_subscriber),
            pytest.raises(RuntimeError, match="not connected"),
        ):
            await send_command(db, "aabbccddeeff", "get_vbatt")

    @pytest.mark.asyncio
    async def test_reboot_command(self):
        """reboot command should work (doesn't require ECU)."""
        from app.services.device_command_service import send_command

        db = AsyncMock()
        device = _mock_device(ecu_status="offline")  # ECU off is fine for reboot

        mock_livelink = AsyncMock()
        mock_livelink.get_device_by_id = AsyncMock(return_value=device)

        mock_subscriber = MagicMock()
        mock_subscriber.is_connected = True
        mock_subscriber.send_device_command = AsyncMock()

        with (
            patch(
                "app.services.device_command_service.LiveLinkService", return_value=mock_livelink
            ),
            patch("app.services.mqtt_subscriber.mqtt_subscriber", mock_subscriber),
        ):
            result = await send_command(db, "aabbccddeeff", "reboot")

        assert result["status"] == "sent"
        mock_subscriber.send_device_command.assert_called_once()


class TestMQTTSubscriberPublish:
    """Test MQTT subscriber publish capabilities."""

    @pytest.mark.asyncio
    async def test_publish_with_connected_client(self):
        """Publishing with connected client should work."""
        from app.services.mqtt_subscriber import MQTTSubscriber

        subscriber = MQTTSubscriber()
        mock_client = AsyncMock()
        subscriber._client = mock_client
        subscriber._connection_status = "connected"

        await subscriber.publish("test/topic", '{"key": "value"}')
        mock_client.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_without_client_raises(self):
        """Publishing without client should raise RuntimeError."""
        from app.services.mqtt_subscriber import MQTTSubscriber

        subscriber = MQTTSubscriber()
        subscriber._client = None

        with pytest.raises(RuntimeError, match="not connected"):
            await subscriber.publish("test/topic", '{"key": "value"}')

    @pytest.mark.asyncio
    async def test_send_device_command_builds_topic(self):
        """send_device_command should build correct topic."""
        from app.services.mqtt_subscriber import MQTTSubscriber

        subscriber = MQTTSubscriber()
        mock_client = AsyncMock()
        subscriber._client = mock_client
        subscriber._topic_prefix = "wican"
        subscriber._connection_status = "connected"

        await subscriber.send_device_command("aabbccddeeff", '{"get_vbatt":""}')

        call_args = mock_client.publish.call_args
        assert call_args[0][0] == "wican/aabbccddeeff/cmd"

    def test_is_connected_property(self):
        """is_connected should reflect client and status."""
        from app.services.mqtt_subscriber import MQTTSubscriber

        subscriber = MQTTSubscriber()
        assert subscriber.is_connected is False

        subscriber._client = MagicMock()
        subscriber._connection_status = "connected"
        assert subscriber.is_connected is True

        subscriber._connection_status = "error"
        assert subscriber.is_connected is False

        subscriber._connection_status = "connected"
        subscriber._client = None
        assert subscriber.is_connected is False

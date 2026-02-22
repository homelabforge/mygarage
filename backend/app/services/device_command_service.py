"""Device command service for sending MQTT commands to WiCAN devices.

Supported WiCAN commands (verified from firmware source main/mqtt.c):
- get_vbatt: Request battery voltage (response arrives via normal battery handler)
- get_autopid_data: Trigger one-shot AutoPID poll (data arrives on normal topic)
- reboot: Reboot the device (response: {"rsp": "ok"} then reboots)

Note: AutoPID on/off is NOT yet implemented in firmware (Discussion #571).
"""

import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.livelink_service import LiveLinkService

logger = logging.getLogger(__name__)

# Commands supported by WiCAN firmware
SUPPORTED_COMMANDS: dict[str, dict[str, Any]] = {
    "get_vbatt": {
        "description": "Request battery voltage",
        "payload": json.dumps({"get_vbatt": ""}),
        "requires_ecu": False,
    },
    "get_autopid_data": {
        "description": "Trigger one-shot AutoPID data poll",
        "payload": json.dumps({"get_autopid_data": ""}),
        "requires_ecu": True,
    },
    "reboot": {
        "description": "Reboot the WiCAN device",
        "payload": json.dumps({"reboot": ""}),
        "requires_ecu": False,
    },
}


async def send_command(
    db: AsyncSession,
    device_id: str,
    command: str,
) -> dict[str, str]:
    """Send a command to a WiCAN device via MQTT.

    Args:
        db: Database session.
        device_id: Target device ID (12-char hex).
        command: Command name (must be in SUPPORTED_COMMANDS).

    Returns:
        Dict with status and message.

    Raises:
        ValueError: If command is unknown or device is not eligible.
        RuntimeError: If MQTT subscriber is not connected.
    """
    # Validate command
    if command not in SUPPORTED_COMMANDS:
        raise ValueError(
            f"Unknown command '{command}'. Supported: {', '.join(SUPPORTED_COMMANDS.keys())}"
        )

    cmd_info = SUPPORTED_COMMANDS[command]

    # Check device exists and is online
    livelink_service = LiveLinkService(db)
    device = await livelink_service.get_device_by_id(device_id)
    if not device:
        raise ValueError(f"Device {device_id} not found")

    if device.device_status != "online":
        raise ValueError(
            f"Device {device_id} is {device.device_status}, must be online to send commands"
        )

    # Check ECU requirement
    if cmd_info["requires_ecu"] and device.ecu_status != "online":
        raise ValueError(
            f"Command '{command}' requires ECU to be online (current: {device.ecu_status})"
        )

    # Check MQTT connectivity
    from app.services.mqtt_subscriber import mqtt_subscriber

    if not mqtt_subscriber.is_connected:
        raise RuntimeError("MQTT subscriber is not connected")

    # Send the command
    await mqtt_subscriber.send_device_command(device_id, cmd_info["payload"])

    return {
        "status": "sent",
        "message": f"Command '{command}' sent to device {device_id}",
    }

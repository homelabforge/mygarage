"""LiveLink scheduled background tasks."""

import logging
from datetime import UTC, datetime, timedelta

from app.database import AsyncSessionLocal
from app.services.firmware_service import FirmwareService
from app.services.livelink_service import LiveLinkService
from app.services.notifications.dispatcher import NotificationDispatcher
from app.services.session_service import SessionService
from app.services.settings_service import SettingsService
from app.services.telemetry_service import TelemetryService

logger = logging.getLogger(__name__)


async def check_session_timeouts():
    """Check for and close stale drive sessions.

    Runs every minute. Closes sessions where the device hasn't been
    seen for longer than the configured timeout period.
    """
    async with AsyncSessionLocal() as db:
        try:
            # Get timeout setting
            livelink_service = LiveLinkService(db)
            if not await livelink_service.is_enabled():
                return

            timeout_minutes = await livelink_service.get_session_timeout_minutes()

            # Close stale sessions
            session_service = SessionService(db)
            closed = await session_service.check_session_timeouts(timeout_minutes)

            if closed:
                logger.info(
                    "Closed %d stale sessions (timeout: %d minutes)",
                    len(closed),
                    timeout_minutes,
                )

        except Exception as e:
            logger.error("Error checking session timeouts: %s", e)


async def check_device_offline_status():
    """Check for devices that have gone offline and send notifications.

    Runs every 5 minutes. Marks devices as offline if they haven't been
    seen for longer than the configured timeout period.
    """
    async with AsyncSessionLocal() as db:
        try:
            livelink_service = LiveLinkService(db)
            if not await livelink_service.is_enabled():
                return

            # Get timeout setting
            offline_timeout = await livelink_service.get_device_offline_timeout_minutes()
            cutoff = datetime.now(UTC) - timedelta(minutes=offline_timeout)

            # Check notification setting
            notify_enabled = await _get_bool_setting(db, "livelink_notify_device_offline", True)

            # Get all online devices that haven't been seen recently
            devices = await livelink_service.list_devices()
            dispatcher = NotificationDispatcher(db)

            for device in devices:
                if device.device_status == "online" and device.last_seen:
                    if device.last_seen < cutoff:
                        # Mark device as offline
                        await livelink_service.set_device_offline(device.device_id)
                        logger.info("Marked device %s as offline", device.device_id)

                        # Send notification if enabled
                        if notify_enabled and device.enabled:
                            # Get vehicle name if linked
                            vehicle_name = None
                            if device.vin:
                                from sqlalchemy import select

                                from app.models.vehicle import Vehicle

                                result = await db.execute(
                                    select(Vehicle.year, Vehicle.make, Vehicle.model).where(
                                        Vehicle.vin == device.vin
                                    )
                                )
                                row = result.first()
                                if row:
                                    vehicle_name = f"{row[0]} {row[1]} {row[2]}"

                            offline_minutes = int(
                                (datetime.now(UTC) - device.last_seen).total_seconds() / 60
                            )
                            await dispatcher.notify_livelink_device_offline(
                                device_id=device.device_id,
                                vehicle_name=vehicle_name,
                                offline_minutes=offline_minutes,
                            )

            await db.commit()

        except Exception as e:
            logger.error("Error checking device offline status: %s", e)


async def check_firmware_updates():
    """Check for WiCAN firmware updates and notify.

    Runs daily at 3 AM. Fetches latest release from GitHub and
    sends notifications for devices with available updates.
    """
    async with AsyncSessionLocal() as db:
        try:
            livelink_service = LiveLinkService(db)
            if not await livelink_service.is_enabled():
                return

            # Check if firmware check is enabled
            check_enabled = await _get_bool_setting(db, "livelink_firmware_check_enabled", True)
            if not check_enabled:
                return

            # Check for updates
            firmware_service = FirmwareService(db)
            update_info = await firmware_service.check_firmware_updates()

            if "error" in update_info:
                logger.warning("Firmware check failed: %s", update_info["error"])
                return

            latest_version = update_info.get("latest_version")
            if not latest_version:
                return

            logger.info("Firmware check complete: latest version is %s", latest_version)

            # Check notification setting
            notify_enabled = await _get_bool_setting(db, "livelink_notify_firmware_update", True)
            if not notify_enabled:
                return

            # Get devices needing updates
            devices_needing_update = await firmware_service.get_devices_needing_update()

            if devices_needing_update:
                dispatcher = NotificationDispatcher(db)

                for device_info in devices_needing_update:
                    await dispatcher.notify_livelink_firmware_update(
                        device_id=device_info["device_id"],
                        current_version=device_info["current_version"],
                        latest_version=device_info["latest_version"],
                        release_url=device_info.get("release_url"),
                    )

                logger.info(
                    "Sent firmware update notifications for %d devices",
                    len(devices_needing_update),
                )

        except Exception as e:
            logger.error("Error checking firmware updates: %s", e)


async def prune_old_telemetry():
    """Prune old telemetry data based on retention settings.

    Runs daily at 4 AM. Deletes telemetry data older than the
    configured retention period (default 90 days).
    """
    async with AsyncSessionLocal() as db:
        try:
            livelink_service = LiveLinkService(db)
            if not await livelink_service.is_enabled():
                return

            retention_days = await livelink_service.get_retention_days()

            telemetry_service = TelemetryService(db)
            deleted_count = await telemetry_service.prune_old_telemetry(retention_days)

            if deleted_count > 0:
                logger.info(
                    "Pruned %d telemetry records older than %d days",
                    deleted_count,
                    retention_days,
                )

        except Exception as e:
            logger.error("Error pruning old telemetry: %s", e)


async def generate_daily_summaries():
    """Generate daily summary aggregates for telemetry data.

    Runs daily at 1 AM. Creates/updates summary records for the
    previous day's telemetry data.
    """
    async with AsyncSessionLocal() as db:
        try:
            livelink_service = LiveLinkService(db)
            if not await livelink_service.is_enabled():
                return

            # Check if aggregation is enabled
            aggregation_enabled = await _get_bool_setting(
                db, "livelink_daily_aggregation_enabled", True
            )
            if not aggregation_enabled:
                return

            # Generate summaries for yesterday
            yesterday = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday -= timedelta(days=1)

            telemetry_service = TelemetryService(db)
            summary_count = await telemetry_service.generate_daily_summary(yesterday)

            if summary_count > 0:
                logger.info(
                    "Generated %d daily summary records for %s",
                    summary_count,
                    yesterday.date(),
                )

        except Exception as e:
            logger.error("Error generating daily summaries: %s", e)


async def _get_bool_setting(db, key: str, default: bool = False) -> bool:
    """Get a boolean setting value."""
    setting = await SettingsService.get(db, key)
    if not setting or not setting.value:
        return default
    return setting.value.lower() in ("true", "1", "yes")


# =============================================================================
# MQTT Subscriber Management Functions
# =============================================================================


async def is_mqtt_enabled() -> bool:
    """Check if MQTT is enabled in settings."""
    async with AsyncSessionLocal() as db:
        setting = await SettingsService.get(db, "livelink_mqtt_enabled")
        return setting is not None and setting.value == "true"


async def start_mqtt_subscriber() -> None:
    """Start the MQTT subscriber if enabled."""
    from app.services.mqtt_subscriber import mqtt_subscriber

    try:
        if await is_mqtt_enabled():
            await mqtt_subscriber.start()
            logger.info("MQTT subscriber started successfully")
        else:
            logger.info("MQTT subscriber disabled in settings")
    except Exception as e:
        logger.error("Failed to start MQTT subscriber: %s", e)


async def stop_mqtt_subscriber() -> None:
    """Stop the MQTT subscriber."""
    from app.services.mqtt_subscriber import mqtt_subscriber

    try:
        await mqtt_subscriber.stop()
    except Exception as e:
        logger.error("Error stopping MQTT subscriber: %s", e)


async def restart_mqtt_subscriber() -> None:
    """Restart the MQTT subscriber (for config changes)."""
    await stop_mqtt_subscriber()
    await start_mqtt_subscriber()


def get_mqtt_status() -> dict:
    """Get MQTT subscriber status."""
    from app.services.mqtt_subscriber import mqtt_subscriber

    return mqtt_subscriber.status

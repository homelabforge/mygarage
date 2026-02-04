"""LiveLink service for token generation and device management."""

import hashlib
import logging
import secrets
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)

# Token prefix for easy identification
TOKEN_PREFIX = "ll_"
TOKEN_LENGTH = 32  # 32 bytes = 256 bits of entropy


class LiveLinkService:
    """Service for LiveLink token management and device operations."""

    def __init__(self, db: AsyncSession):
        """Initialize with database session."""
        self.db = db

    # =========================================================================
    # Token Management
    # =========================================================================

    @staticmethod
    def generate_token() -> str:
        """Generate a new API token.

        Returns the plaintext token (shown to user once).
        Token format: ll_<base64url-encoded-random-bytes>
        """
        random_bytes = secrets.token_urlsafe(TOKEN_LENGTH)
        return f"{TOKEN_PREFIX}{random_bytes}"

    @staticmethod
    def hash_token(token: str) -> str:
        """Hash a token for storage using SHA-256.

        API tokens are high-entropy secrets, so SHA-256 is appropriate
        (unlike passwords which need slow hashes like Argon2).
        """
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def mask_token(token: str) -> str:
        """Mask a token for display.

        Returns first 6 and last 4 characters with *** in between.
        """
        if len(token) < 12:
            return "***"
        return f"{token[:6]}***{token[-4:]}"

    async def generate_global_token(self) -> str:
        """Generate and store a new global API token.

        Returns the plaintext token (shown to user once).
        The token is immediately hashed and stored.
        """
        token = self.generate_token()
        token_hash = self.hash_token(token)

        await SettingsService.set(
            self.db,
            "livelink_global_token_hash",
            token_hash,
            category="livelink",
            description="SHA-256 hash of global LiveLink API token",
        )
        await self.db.commit()

        logger.info("Generated new global LiveLink token")
        return token

    async def validate_global_token(self, token: str) -> bool:
        """Validate a token against the stored global token hash."""
        stored_hash = await SettingsService.get(self.db, "livelink_global_token_hash")
        if not stored_hash or not stored_hash.value:
            return False

        provided_hash = self.hash_token(token)
        return secrets.compare_digest(provided_hash, stored_hash.value)

    async def generate_device_token(self, device_id: str) -> str | None:
        """Generate and store a per-device API token.

        Returns the plaintext token (shown to user once), or None if device not found.
        """
        device = await self.get_device_by_id(device_id)
        if not device:
            return None

        token = self.generate_token()
        token_hash = self.hash_token(token)

        device.device_token_hash = token_hash
        device.updated_at = datetime.now(UTC)
        await self.db.commit()

        logger.info("Generated new device token for device %s", device_id)
        return token

    async def revoke_device_token(self, device_id: str) -> bool:
        """Revoke a per-device token (falls back to global token).

        Returns True if successful, False if device not found.
        """
        device = await self.get_device_by_id(device_id)
        if not device:
            return False

        device.device_token_hash = None
        device.updated_at = datetime.now(UTC)
        await self.db.commit()

        logger.info("Revoked device token for device %s", device_id)
        return True

    async def validate_device_token(self, device_id: str, token: str) -> bool:
        """Validate a token against a device's per-device token hash."""
        device = await self.get_device_by_id(device_id)
        if not device or not device.device_token_hash:
            return False

        provided_hash = self.hash_token(token)
        return secrets.compare_digest(provided_hash, device.device_token_hash)

    async def validate_token(self, token: str, device_id: str | None = None) -> bool:
        """Validate a token (per-device first, then global).

        Args:
            token: The Bearer token to validate
            device_id: Optional device_id from payload for per-device token check

        Returns:
            True if token is valid
        """
        # Check per-device token first if device_id provided
        if device_id:
            if await self.validate_device_token(device_id, token):
                return True

        # Fall back to global token
        return await self.validate_global_token(token)

    # =========================================================================
    # Device Management
    # =========================================================================

    async def get_device_by_id(self, device_id: str) -> LiveLinkDevice | None:
        """Get a device by its device_id."""
        result = await self.db.execute(
            select(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id)
        )
        return result.scalar_one_or_none()

    async def get_device_by_vin(self, vin: str) -> LiveLinkDevice | None:
        """Get a device linked to a vehicle."""
        result = await self.db.execute(select(LiveLinkDevice).where(LiveLinkDevice.vin == vin))
        return result.scalar_one_or_none()

    async def list_devices(self) -> list[LiveLinkDevice]:
        """List all discovered devices."""
        result = await self.db.execute(
            select(LiveLinkDevice).order_by(LiveLinkDevice.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_device_id_by_token(self, _authorization: str | None) -> str | None:
        """Get the most recently active device ID for telemetry-only payloads.

        When WiCAN sends telemetry without a status block, we need to identify
        the device from context. This method returns the most recently seen
        online device, which works well for single-device setups.

        For multi-device setups with the global token, this returns the most
        recently active device. For better accuracy, use per-device tokens.

        Args:
            authorization: The Authorization header (used for logging/future per-device lookup)

        Returns:
            device_id of the most recently seen online device, or None if no devices found
        """
        # Find the most recently seen device that's online and enabled
        result = await self.db.execute(
            select(LiveLinkDevice)
            .where(
                LiveLinkDevice.enabled == True,  # noqa: E712
                LiveLinkDevice.device_status == "online",
            )
            .order_by(LiveLinkDevice.last_seen.desc())
            .limit(1)
        )
        device = result.scalar_one_or_none()
        if device:
            return device.device_id

        # Fallback: any enabled device (even if offline) sorted by last_seen
        result = await self.db.execute(
            select(LiveLinkDevice)
            .where(LiveLinkDevice.enabled == True)  # noqa: E712
            .order_by(LiveLinkDevice.last_seen.desc().nullslast())
            .limit(1)
        )
        device = result.scalar_one_or_none()
        return device.device_id if device else None

    async def auto_discover_device(
        self,
        device_id: str,
        hw_version: str | None = None,
        fw_version: str | None = None,
        git_version: str | None = None,
        sta_ip: str | None = None,
    ) -> tuple[LiveLinkDevice, bool]:
        """Auto-discover a new device or get existing one.

        Returns (device, is_new) tuple.
        """
        existing = await self.get_device_by_id(device_id)
        if existing:
            # Update device info from payload
            existing.hw_version = hw_version or existing.hw_version
            existing.fw_version = fw_version or existing.fw_version
            existing.git_version = git_version or existing.git_version
            existing.sta_ip = sta_ip or existing.sta_ip
            existing.updated_at = datetime.now(UTC)
            return existing, False

        # Create new unlinked device
        device = LiveLinkDevice(
            device_id=device_id,
            vin=None,  # Unlinked
            hw_version=hw_version,
            fw_version=fw_version,
            git_version=git_version,
            sta_ip=sta_ip,
            device_status="online",
            ecu_status="unknown",
            enabled=True,
            last_seen=datetime.now(UTC),
        )
        self.db.add(device)
        await self.db.flush()

        logger.info("Auto-discovered new WiCAN device: %s", device_id)
        return device, True

    async def link_device_to_vehicle(self, device_id: str, vin: str) -> bool:
        """Link a device to a vehicle.

        Returns True if successful, False if device not found.
        """
        device = await self.get_device_by_id(device_id)
        if not device:
            return False

        device.vin = vin
        device.updated_at = datetime.now(UTC)
        await self.db.commit()

        logger.info("Linked device %s to vehicle %s", device_id, vin)
        return True

    async def unlink_device(self, device_id: str) -> bool:
        """Unlink a device from its vehicle (ready for re-linking).

        Historical data stays with the vehicle.
        Returns True if successful, False if device not found.
        """
        device = await self.get_device_by_id(device_id)
        if not device:
            return False

        old_vin = device.vin
        device.vin = None
        device.current_session_id = None  # Clear any active session
        device.updated_at = datetime.now(UTC)
        await self.db.commit()

        logger.info("Unlinked device %s from vehicle %s", device_id, old_vin)
        return True

    async def update_device(
        self,
        device_id: str,
        label: str | None = None,
        vin: str | None = None,
        enabled: bool | None = None,
    ) -> LiveLinkDevice | None:
        """Update device settings."""
        device = await self.get_device_by_id(device_id)
        if not device:
            return None

        if label is not None:
            device.label = label
        if vin is not None:
            device.vin = vin if vin else None
        if enabled is not None:
            device.enabled = enabled

        device.updated_at = datetime.now(UTC)
        await self.db.commit()

        return device

    async def delete_device(self, device_id: str) -> bool:
        """Delete a device record.

        Historical telemetry, sessions, and DTCs are retained (keyed on vehicle_id).
        Returns True if device was deleted, False if not found.
        """
        device = await self.get_device_by_id(device_id)
        if not device:
            return False

        await self.db.delete(device)
        await self.db.commit()

        logger.info("Deleted device %s", device_id)
        return True

    async def update_device_status(
        self,
        device_id: str,
        device_status: str | None = None,
        ecu_status: str | None = None,
        rssi: int | None = None,
        battery_voltage: float | None = None,
        sta_ip: str | None = None,
    ) -> None:
        """Update device status fields from payload."""
        await self.db.execute(
            update(LiveLinkDevice)
            .where(LiveLinkDevice.device_id == device_id)
            .values(
                device_status=device_status or LiveLinkDevice.device_status,
                ecu_status=ecu_status or LiveLinkDevice.ecu_status,
                rssi=rssi if rssi is not None else LiveLinkDevice.rssi,
                battery_voltage=battery_voltage
                if battery_voltage is not None
                else LiveLinkDevice.battery_voltage,
                sta_ip=sta_ip or LiveLinkDevice.sta_ip,
                last_seen=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )

    async def set_device_offline(self, device_id: str) -> None:
        """Mark a device as offline."""
        await self.db.execute(
            update(LiveLinkDevice)
            .where(LiveLinkDevice.device_id == device_id)
            .values(
                device_status="offline",
                updated_at=datetime.now(UTC),
            )
        )

    # =========================================================================
    # Settings Helpers
    # =========================================================================

    async def is_enabled(self) -> bool:
        """Check if LiveLink is globally enabled."""
        setting = await SettingsService.get(self.db, "livelink_enabled")
        return setting is not None and setting.value == "true"

    async def get_session_timeout_minutes(self) -> int:
        """Get session timeout in minutes."""
        setting = await SettingsService.get(self.db, "livelink_session_timeout_minutes")
        return int(setting.value) if setting and setting.value else 5

    async def get_device_offline_timeout_minutes(self) -> int:
        """Get device offline timeout in minutes."""
        setting = await SettingsService.get(self.db, "livelink_device_offline_timeout_minutes")
        return int(setting.value) if setting and setting.value else 15

    async def get_retention_days(self) -> int:
        """Get telemetry retention period in days."""
        setting = await SettingsService.get(self.db, "livelink_telemetry_retention_days")
        return int(setting.value) if setting and setting.value else 90

    async def get_alert_cooldown_minutes(self) -> int:
        """Get alert cooldown period in minutes."""
        setting = await SettingsService.get(self.db, "livelink_alert_cooldown_minutes")
        return int(setting.value) if setting and setting.value else 30

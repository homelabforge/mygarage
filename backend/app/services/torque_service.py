"""Torque Pro source lifecycle: create a device row + resolve a path token."""

import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.services.livelink_service import LiveLinkService


class TorqueService:
    """Service for Torque Pro source (device) creation and token resolution."""

    def __init__(self, db: AsyncSession):
        """Initialize with database session."""
        self.db = db

    async def create_source(
        self,
        vin: str,
        label: str | None = None,
        torque_device_id: str | None = None,
    ) -> tuple[LiveLinkDevice, str]:
        """Create a kind='torque' device linked to a vehicle.

        Returns (device, raw_token) — the raw token is shown to the user once.
        """
        device_id = "tq_" + secrets.token_hex(4)  # 8 hex chars → fits VARCHAR(20)
        raw_token = LiveLinkService.generate_token()
        device = LiveLinkDevice(
            device_id=device_id,
            vin=vin,
            kind="torque",
            torque_device_id=torque_device_id,
            label=label or "Torque Pro",
            device_token_hash=LiveLinkService.hash_token(raw_token),
            enabled=True,
            device_status="unknown",
            ecu_status="unknown",
        )
        self.db.add(device)
        await self.db.flush()
        return device, raw_token

    async def resolve_by_token(self, token: str) -> LiveLinkDevice | None:
        """Resolve a raw Torque path token to its device (kind='torque', enabled only)."""
        token_hash = LiveLinkService.hash_token(token)
        result = await self.db.execute(
            select(LiveLinkDevice).where(
                LiveLinkDevice.device_token_hash == token_hash,
                LiveLinkDevice.kind == "torque",
                LiveLinkDevice.enabled.is_(True),
            )
        )
        return result.scalar_one_or_none()

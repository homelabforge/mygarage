"""Firmware service for WiCAN firmware update checking."""

import logging
import re
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_firmware_cache import LiveLinkFirmwareCache

logger = logging.getLogger(__name__)

# GitHub API endpoint for WiCAN firmware releases
GITHUB_RELEASES_URL = "https://api.github.com/repos/meatpiHQ/wican-fw/releases/latest"

# Minimum firmware version for HTTPS POST support
MIN_FIRMWARE_VERSION = "4.40"


class FirmwareService:
    """Service for WiCAN firmware version checking."""

    def __init__(self, db: AsyncSession):
        """Initialize with database session."""
        self.db = db

    async def check_firmware_updates(self) -> dict:
        """Check GitHub for latest WiCAN firmware release.

        Updates the firmware cache table with the latest version info.

        Returns:
            Dict with latest version info or error message
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    GITHUB_RELEASES_URL,
                    headers={
                        "Accept": "application/vnd.github.v3+json",
                        "User-Agent": "MyGarage-LiveLink/1.0",
                    },
                )
                response.raise_for_status()
                release_data = response.json()

        except httpx.HTTPStatusError as e:
            logger.error("GitHub API error: %s", e)
            return {"error": f"GitHub API error: {e.response.status_code}"}
        except httpx.RequestError as e:
            logger.error("GitHub API request failed: %s", e)
            return {"error": f"Request failed: {e}"}

        # Parse release data
        tag_name = release_data.get("tag_name", "")
        version = self._extract_version(tag_name)
        html_url = release_data.get("html_url", "")
        body = release_data.get("body", "")

        # Update cache
        await self._update_cache(
            latest_version=version,
            latest_tag=tag_name,
            release_url=html_url,
            release_notes=body[:2000] if body else None,  # Truncate notes
        )

        logger.info("Firmware check complete: latest version is %s", version)

        return {
            "latest_version": version,
            "latest_tag": tag_name,
            "release_url": html_url,
            "release_notes": body[:500] if body else None,  # Summary for response
        }

    def _extract_version(self, tag: str) -> str:
        """Extract version number from git tag.

        Examples:
            "v4.45p" -> "4.45"
            "v4.50" -> "4.50"
            "4.45p" -> "4.45"
        """
        # Remove 'v' prefix and 'p' suffix
        version = tag.strip().lstrip("v").rstrip("p")

        # Extract just the version number
        match = re.search(r"(\d+\.\d+(?:\.\d+)?)", version)
        return match.group(1) if match else version

    async def _update_cache(
        self,
        latest_version: str,
        latest_tag: str,
        release_url: str,
        release_notes: str | None,
    ) -> None:
        """Update the firmware cache table."""
        # Get or create singleton row
        result = await self.db.execute(
            select(LiveLinkFirmwareCache).where(LiveLinkFirmwareCache.id == 1)
        )
        cache = result.scalar_one_or_none()

        if cache:
            cache.latest_version = latest_version
            cache.latest_tag = latest_tag
            cache.release_url = release_url
            cache.release_notes = release_notes
            cache.checked_at = datetime.now(UTC)
        else:
            cache = LiveLinkFirmwareCache(
                id=1,
                latest_version=latest_version,
                latest_tag=latest_tag,
                release_url=release_url,
                release_notes=release_notes,
                checked_at=datetime.now(UTC),
            )
            self.db.add(cache)

        await self.db.commit()

    async def get_cached_firmware_info(self) -> dict | None:
        """Get cached firmware information.

        Returns:
            Dict with firmware info or None if not cached
        """
        result = await self.db.execute(
            select(LiveLinkFirmwareCache).where(LiveLinkFirmwareCache.id == 1)
        )
        cache = result.scalar_one_or_none()

        if not cache or not cache.latest_version:
            return None

        return {
            "latest_version": cache.latest_version,
            "latest_tag": cache.latest_tag,
            "release_url": cache.release_url,
            "release_notes": cache.release_notes,
            "checked_at": cache.checked_at,
        }

    async def get_devices_needing_update(self) -> list[dict]:
        """Get list of devices that have firmware updates available.

        Returns:
            List of dicts with device_id, current_version, latest_version
        """
        # Get cached latest version
        cache_info = await self.get_cached_firmware_info()
        if not cache_info:
            return []

        latest_version = cache_info["latest_version"]

        # Get all devices with firmware version info
        result = await self.db.execute(
            select(LiveLinkDevice).where(LiveLinkDevice.fw_version.isnot(None))
        )
        devices = result.scalars().all()

        devices_needing_update = []
        for device in devices:
            if device.fw_version and self.compare_versions(device.fw_version, latest_version) < 0:
                devices_needing_update.append(
                    {
                        "device_id": device.device_id,
                        "label": device.label,
                        "current_version": device.fw_version,
                        "latest_version": latest_version,
                        "release_url": cache_info.get("release_url"),
                        "sta_ip": device.sta_ip,
                    }
                )

        return devices_needing_update

    @staticmethod
    def compare_versions(version1: str, version2: str) -> int:
        """Compare two version strings.

        Returns:
            -1 if version1 < version2
            0 if version1 == version2
            1 if version1 > version2
        """
        # Extract just numbers
        v1_match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", version1)
        v2_match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", version2)

        if not v1_match or not v2_match:
            # Fall back to string comparison
            return (version1 > version2) - (version1 < version2)

        v1_parts = [int(v1_match.group(1)), int(v1_match.group(2)), int(v1_match.group(3) or 0)]
        v2_parts = [int(v2_match.group(1)), int(v2_match.group(2)), int(v2_match.group(3) or 0)]

        for p1, p2 in zip(v1_parts, v2_parts):
            if p1 < p2:
                return -1
            if p1 > p2:
                return 1

        return 0

    @staticmethod
    def is_firmware_compatible(version: str) -> bool:
        """Check if firmware version supports HTTPS POST.

        Args:
            version: Firmware version string

        Returns:
            True if version >= MIN_FIRMWARE_VERSION
        """
        return FirmwareService.compare_versions(version, MIN_FIRMWARE_VERSION) >= 0

    async def check_device_firmware(self, device_id: str) -> dict:
        """Check firmware status for a specific device.

        Returns:
            Dict with update_available, current_version, latest_version, etc.
        """
        # Get device
        result = await self.db.execute(
            select(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id)
        )
        device = result.scalar_one_or_none()

        if not device:
            return {"error": "Device not found"}

        # Get cached latest version
        cache_info = await self.get_cached_firmware_info()

        result_dict = {
            "device_id": device.device_id,
            "hw_version": device.hw_version,
            "current_version": device.fw_version,
            "current_tag": device.git_version,
        }

        if cache_info:
            result_dict["latest_version"] = cache_info["latest_version"]
            result_dict["latest_tag"] = cache_info["latest_tag"]
            result_dict["release_url"] = cache_info["release_url"]
            result_dict["checked_at"] = cache_info["checked_at"]

            if device.fw_version:
                result_dict["update_available"] = (
                    self.compare_versions(device.fw_version, cache_info["latest_version"]) < 0
                )
                result_dict["compatible"] = self.is_firmware_compatible(device.fw_version)
            else:
                result_dict["update_available"] = None
                result_dict["compatible"] = None
        else:
            result_dict["latest_version"] = None
            result_dict["update_available"] = None
            result_dict["compatible"] = None

        return result_dict

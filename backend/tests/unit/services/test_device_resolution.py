"""Unit tests for device resolution from token in telemetry-only payloads."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.livelink_service import LiveLinkService


def _mock_device(device_id: str, enabled: bool = True, token_hash: str | None = None):
    """Create a mock device."""
    device = MagicMock()
    device.device_id = device_id
    device.enabled = enabled
    device.device_token_hash = token_hash
    return device


class TestGetDeviceIdByToken:
    """Test get_device_id_by_token resolution logic."""

    @pytest.fixture
    def service(self):
        """Create a LiveLinkService with mocked database session."""
        db = AsyncMock()
        return LiveLinkService(db)

    @pytest.mark.asyncio
    async def test_per_device_token_resolves_correctly(self, service):
        """Per-device token should resolve to the matching device."""
        token = "ll_test_token_abc"
        token_hash = LiveLinkService.hash_token(token)
        device = _mock_device("aabbccddeeff", token_hash=token_hash)

        # First query (per-device match) returns the device
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = device
        service.db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_device_id_by_token(f"Bearer {token}")
        assert result == "aabbccddeeff"

    @pytest.mark.asyncio
    async def test_single_device_global_token_resolves(self, service):
        """Global token with exactly one enabled device should resolve."""
        device = _mock_device("aabbccddeeff")

        # First query (per-device match) returns None
        no_match = MagicMock()
        no_match.scalar_one_or_none.return_value = None
        # Second query (all enabled) returns one device
        one_device = MagicMock()
        one_device.scalars.return_value.all.return_value = [device]
        service.db.execute = AsyncMock(side_effect=[no_match, one_device])

        result = await service.get_device_id_by_token("Bearer ll_global_token")
        assert result == "aabbccddeeff"

    @pytest.mark.asyncio
    async def test_multiple_devices_global_token_returns_none(self, service):
        """Global token with multiple enabled devices should return None (ambiguous)."""
        device1 = _mock_device("aabbccddeeff")
        device2 = _mock_device("112233445566")

        # First query (per-device match) returns None
        no_match = MagicMock()
        no_match.scalar_one_or_none.return_value = None
        # Second query (all enabled) returns two devices
        two_devices = MagicMock()
        two_devices.scalars.return_value.all.return_value = [device1, device2]
        service.db.execute = AsyncMock(side_effect=[no_match, two_devices])

        result = await service.get_device_id_by_token("Bearer ll_global_token")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_devices_returns_none(self, service):
        """No enabled devices should return None."""
        # First query (per-device match) returns None
        no_match = MagicMock()
        no_match.scalar_one_or_none.return_value = None
        # Second query (all enabled) returns empty
        no_devices = MagicMock()
        no_devices.scalars.return_value.all.return_value = []
        service.db.execute = AsyncMock(side_effect=[no_match, no_devices])

        result = await service.get_device_id_by_token("Bearer ll_some_token")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_authorization_header(self, service):
        """No authorization header should skip per-device check, try global."""
        device = _mock_device("aabbccddeeff")

        # Only the global query runs (no per-device check without token)
        one_device = MagicMock()
        one_device.scalars.return_value.all.return_value = [device]
        service.db.execute = AsyncMock(return_value=one_device)

        result = await service.get_device_id_by_token(None)
        assert result == "aabbccddeeff"

    @pytest.mark.asyncio
    async def test_malformed_authorization_header(self, service):
        """Malformed auth header should skip per-device check."""
        device = _mock_device("aabbccddeeff")

        one_device = MagicMock()
        one_device.scalars.return_value.all.return_value = [device]
        service.db.execute = AsyncMock(return_value=one_device)

        result = await service.get_device_id_by_token("NotBearer token")
        assert result == "aabbccddeeff"

    @pytest.mark.asyncio
    async def test_per_device_token_takes_priority_over_count(self, service):
        """Per-device token match should return even if multiple devices exist."""
        token = "ll_device_specific"
        token_hash = LiveLinkService.hash_token(token)
        device = _mock_device("targetdevice1", token_hash=token_hash)

        # First query (per-device match) finds the device
        match = MagicMock()
        match.scalar_one_or_none.return_value = device
        service.db.execute = AsyncMock(return_value=match)

        result = await service.get_device_id_by_token(f"Bearer {token}")
        assert result == "targetdevice1"
        # Should only have called execute once (per-device match succeeded)
        assert service.db.execute.call_count == 1

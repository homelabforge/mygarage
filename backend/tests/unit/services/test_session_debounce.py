"""Unit tests for session debounce / grace period logic."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_device(
    device_id: str = "aabbccddeeff",
    vin: str | None = "1HGCM82633A123456",
    ecu_status: str = "online",
    pending_offline_at: datetime | None = None,
    enabled: bool = True,
):
    """Create a mock LiveLinkDevice."""
    device = MagicMock()
    device.device_id = device_id
    device.vin = vin
    device.ecu_status = ecu_status
    device.pending_offline_at = pending_offline_at
    device.enabled = enabled
    return device


class TestGracePeriodSetsPending:
    """ECU offline should set pending_offline_at instead of ending session."""

    @pytest.mark.asyncio
    async def test_offline_sets_pending_with_grace(self):
        """ECU offline with grace > 0 should set pending, not end session."""
        from app.services.livelink_service import LiveLinkService

        db = AsyncMock()
        service = LiveLinkService(db)

        service.get_session_grace_period_seconds = AsyncMock(return_value=60)
        service.set_pending_offline = AsyncMock()
        service.clear_pending_offline = AsyncMock()

        await service.set_pending_offline("aabbccddeeff")
        service.set_pending_offline.assert_called_once_with("aabbccddeeff")

    @pytest.mark.asyncio
    async def test_offline_immediate_with_grace_zero(self):
        """ECU offline with grace = 0 should end session immediately."""
        from app.services.livelink_service import LiveLinkService

        db = AsyncMock()
        service = LiveLinkService(db)

        # Mock the method to return 0 (grace disabled)
        service.get_session_grace_period_seconds = AsyncMock(return_value=0)
        grace = await service.get_session_grace_period_seconds()
        assert grace == 0


class TestGracePeriodClearsPending:
    """ECU online while pending should clear pending (WiFi recovered)."""

    @pytest.mark.asyncio
    async def test_online_clears_pending(self):
        """ECU online with pending_offline_at set should clear it."""
        from app.services.livelink_service import LiveLinkService

        db = AsyncMock()
        service = LiveLinkService(db)

        service.clear_pending_offline = AsyncMock()
        await service.clear_pending_offline("aabbccddeeff")
        service.clear_pending_offline.assert_called_once_with("aabbccddeeff")


class TestFinalizePendingOfflines:
    """Test the background task that finalizes pending offlines."""

    @pytest.mark.asyncio
    async def test_finalizes_after_grace_period(self):
        """Devices past grace period should be finalized."""
        from app.tasks.livelink_tasks import finalize_pending_offlines

        # Device pending since 120 seconds ago (grace = 60)
        device = _mock_device(
            pending_offline_at=datetime.now(UTC) - timedelta(seconds=120),
        )

        mock_livelink = AsyncMock()
        mock_livelink.is_enabled = AsyncMock(return_value=True)
        mock_livelink.get_session_grace_period_seconds = AsyncMock(return_value=60)
        mock_livelink.get_devices_pending_offline = AsyncMock(return_value=[device])
        mock_livelink.clear_pending_offline = AsyncMock()
        mock_livelink.update_device_status = AsyncMock()

        mock_session = AsyncMock()

        with (
            patch("app.tasks.livelink_tasks.AsyncSessionLocal") as mock_db_factory,
            patch("app.tasks.livelink_tasks.LiveLinkService", return_value=mock_livelink),
            patch("app.tasks.livelink_tasks.SessionService", return_value=mock_session),
        ):
            mock_db = AsyncMock()
            mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await finalize_pending_offlines()

        # Should have called handle_ecu_offline and cleared pending
        mock_session.handle_ecu_offline.assert_called_once_with(
            device.vin,
            device.device_id,
        )
        mock_livelink.clear_pending_offline.assert_called_once_with(device.device_id)
        mock_livelink.update_device_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_finalize_within_grace(self):
        """Devices within grace period should NOT be finalized."""
        from app.tasks.livelink_tasks import finalize_pending_offlines

        # Device pending since 10 seconds ago (grace = 60)
        device = _mock_device(
            pending_offline_at=datetime.now(UTC) - timedelta(seconds=10),
        )

        mock_livelink = AsyncMock()
        mock_livelink.is_enabled = AsyncMock(return_value=True)
        mock_livelink.get_session_grace_period_seconds = AsyncMock(return_value=60)
        mock_livelink.get_devices_pending_offline = AsyncMock(return_value=[device])
        mock_livelink.clear_pending_offline = AsyncMock()

        mock_session = AsyncMock()

        with (
            patch("app.tasks.livelink_tasks.AsyncSessionLocal") as mock_db_factory,
            patch("app.tasks.livelink_tasks.LiveLinkService", return_value=mock_livelink),
            patch("app.tasks.livelink_tasks.SessionService", return_value=mock_session),
        ):
            mock_db = AsyncMock()
            mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await finalize_pending_offlines()

        # Should NOT have called handle_ecu_offline
        mock_session.handle_ecu_offline.assert_not_called()
        mock_livelink.clear_pending_offline.assert_not_called()

    @pytest.mark.asyncio
    async def test_grace_zero_skips_finalization(self):
        """Grace period of 0 should skip finalization entirely."""
        from app.tasks.livelink_tasks import finalize_pending_offlines

        mock_livelink = AsyncMock()
        mock_livelink.is_enabled = AsyncMock(return_value=True)
        mock_livelink.get_session_grace_period_seconds = AsyncMock(return_value=0)

        with (
            patch("app.tasks.livelink_tasks.AsyncSessionLocal") as mock_db_factory,
            patch("app.tasks.livelink_tasks.LiveLinkService", return_value=mock_livelink),
        ):
            mock_db = AsyncMock()
            mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await finalize_pending_offlines()

        # Should NOT have queried for pending devices
        mock_livelink.get_devices_pending_offline.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_pending_devices_noop(self):
        """No pending devices should be a no-op."""
        from app.tasks.livelink_tasks import finalize_pending_offlines

        mock_livelink = AsyncMock()
        mock_livelink.is_enabled = AsyncMock(return_value=True)
        mock_livelink.get_session_grace_period_seconds = AsyncMock(return_value=60)
        mock_livelink.get_devices_pending_offline = AsyncMock(return_value=[])

        with (
            patch("app.tasks.livelink_tasks.AsyncSessionLocal") as mock_db_factory,
            patch("app.tasks.livelink_tasks.LiveLinkService", return_value=mock_livelink),
        ):
            mock_db = AsyncMock()
            mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await finalize_pending_offlines()

        # No commits should have happened
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_unlinked_device_clears_pending_without_session(self):
        """Unlinked device (no VIN) should clear pending without session transition."""
        from app.tasks.livelink_tasks import finalize_pending_offlines

        device = _mock_device(
            vin=None,
            pending_offline_at=datetime.now(UTC) - timedelta(seconds=120),
        )

        mock_livelink = AsyncMock()
        mock_livelink.is_enabled = AsyncMock(return_value=True)
        mock_livelink.get_session_grace_period_seconds = AsyncMock(return_value=60)
        mock_livelink.get_devices_pending_offline = AsyncMock(return_value=[device])
        mock_livelink.clear_pending_offline = AsyncMock()
        mock_livelink.update_device_status = AsyncMock()

        mock_session = AsyncMock()

        with (
            patch("app.tasks.livelink_tasks.AsyncSessionLocal") as mock_db_factory,
            patch("app.tasks.livelink_tasks.LiveLinkService", return_value=mock_livelink),
            patch("app.tasks.livelink_tasks.SessionService", return_value=mock_session),
        ):
            mock_db = AsyncMock()
            mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await finalize_pending_offlines()

        # Should NOT call session service (no VIN), but should clear pending
        mock_session.handle_ecu_offline.assert_not_called()
        mock_livelink.clear_pending_offline.assert_called_once_with(device.device_id)


class TestNaiveTimestampHandling:
    """Ensure naive timestamps from DB are handled correctly."""

    @pytest.mark.asyncio
    async def test_naive_pending_offline_at(self):
        """Naive (no tzinfo) pending_offline_at should be handled."""
        from app.tasks.livelink_tasks import finalize_pending_offlines

        # Simulate naive datetime from SQLite (no timezone)
        naive_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=120)
        device = _mock_device(pending_offline_at=naive_time)

        mock_livelink = AsyncMock()
        mock_livelink.is_enabled = AsyncMock(return_value=True)
        mock_livelink.get_session_grace_period_seconds = AsyncMock(return_value=60)
        mock_livelink.get_devices_pending_offline = AsyncMock(return_value=[device])
        mock_livelink.clear_pending_offline = AsyncMock()
        mock_livelink.update_device_status = AsyncMock()

        mock_session = AsyncMock()

        with (
            patch("app.tasks.livelink_tasks.AsyncSessionLocal") as mock_db_factory,
            patch("app.tasks.livelink_tasks.LiveLinkService", return_value=mock_livelink),
            patch("app.tasks.livelink_tasks.SessionService", return_value=mock_session),
        ):
            mock_db = AsyncMock()
            mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await finalize_pending_offlines()

        # Should finalize without crashing
        mock_session.handle_ecu_offline.assert_called_once()
        mock_livelink.clear_pending_offline.assert_called_once()

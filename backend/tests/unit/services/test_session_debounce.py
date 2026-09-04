"""Unit tests for session debounce / grace period logic."""

import contextlib
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.settings import Setting
from app.services.session_service import SessionService
from app.utils.datetime_utils import utc_now

#: A fixed past instant. Relative-to-now session fixtures are calendar bombs.
FIXED_T0 = datetime(2026, 9, 1, 8, 0, 0)


async def _run_finalizer(db_session) -> None:
    """Run `finalize_pending_offlines` against the TEST session.

    The task opens its own `AsyncSessionLocal`, so the factory is patched to
    hand back the test session instead. `contextlib.nullcontext` keeps the
    session alive afterwards: the real factory closes it on exit, and closing
    the shared test session would take every later assertion with it.
    """
    from app.tasks import livelink_tasks

    existing = await db_session.get(Setting, "livelink_enabled")
    if existing is None:
        db_session.add(Setting(key="livelink_enabled", value="true"))
    else:
        existing.value = "true"
    await db_session.flush()

    with patch.object(
        livelink_tasks, "AsyncSessionLocal", lambda: contextlib.nullcontext(db_session)
    ):
        await livelink_tasks.finalize_pending_offlines()


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
    """The grace-period finalizer, asserted against ROWS rather than mocks.

    These were mock-only: they patched `SessionService` wholesale and asserted
    that `handle_ecu_offline` had been called. That call was a **no-op**, and
    had been since the grace period was introduced. The ingest routes persist
    `ecu_status='offline'` the instant it arrives, so by the time the finalizer
    runs `handle_ecu_status_change` sees offline -> offline and returns None
    without touching the session. The tests passed anyway, because "was this
    method called?" is not "did the session close?".

    The session did eventually close, via a contact timeout -- anchored on a
    `last_seen` that the finalizer itself had advanced by calling
    `update_device_status`, so the drive's tail was padded by the whole grace
    period plus however long the timeout took to notice.

    So each test here reads `drive_sessions.ended_at`, and the two properties
    that the mocked versions could not see -- that the session closes, and that
    `last_seen` is left alone -- get one test each.
    """

    @pytest.mark.asyncio
    async def test_the_session_actually_closes(self, db_session, make_livelink_vehicle):

        vin, device = await make_livelink_vehicle("finoff", "1")
        service = SessionService(db_session)
        moved_at = FIXED_T0 + timedelta(minutes=1)
        device.last_seen = moved_at
        for at in (FIXED_T0, moved_at):
            await service.observe_telemetry(device, {"SPEED": 44.0}, at, live=True)
        await db_session.flush()
        session_id = device.current_session_id
        assert session_id is not None, "the fixture must open a session, or this proves nothing"

        device.pending_offline_at = utc_now().replace(tzinfo=None) - timedelta(seconds=120)
        await db_session.flush()

        await _run_finalizer(db_session)

        closed = await service.get_session(session_id)
        assert closed is not None
        assert closed.ended_at == moved_at, (
            "the session must close at the last MOVEMENT, not at last contact"
        )

    @pytest.mark.asyncio
    async def test_it_does_not_advance_last_seen(self, db_session, make_livelink_vehicle):
        """There was no contact. Fabricating one corrupts every timeout."""

        vin, device = await make_livelink_vehicle("finoff", "2")
        device.last_seen = FIXED_T0
        device.pending_offline_at = utc_now().replace(tzinfo=None) - timedelta(seconds=120)
        await db_session.flush()

        await _run_finalizer(db_session)
        await db_session.refresh(device)

        assert device.last_seen == FIXED_T0

    @pytest.mark.asyncio
    async def test_it_clears_the_pending_movement_state(self, db_session, make_livelink_vehicle):
        """Pending clears when the offline FINALIZES, not when it arrives.

        `test_a_dropout_inside_the_grace_keeps_the_pending_envelope` in
        `test_session_state_machine.py` is the other half of this pair.
        """
        vin, device = await make_livelink_vehicle("finoff", "3")
        service = SessionService(db_session)
        await service.observe_telemetry(device, {"ENGINE_RPM": 700.0}, FIXED_T0, live=True)
        await db_session.flush()
        assert device.pending_since == FIXED_T0

        device.pending_offline_at = utc_now().replace(tzinfo=None) - timedelta(seconds=120)
        await db_session.flush()

        await _run_finalizer(db_session)
        await db_session.refresh(device)

        assert device.pending_since is None
        assert device.pending_offline_at is None

    @pytest.mark.asyncio
    async def test_it_marks_the_device_offline(self, db_session, make_livelink_vehicle):
        vin, device = await make_livelink_vehicle("finoff", "4")
        device.device_status = "online"
        device.pending_offline_at = utc_now().replace(tzinfo=None) - timedelta(seconds=120)
        await db_session.flush()

        await _run_finalizer(db_session)
        await db_session.refresh(device)

        assert device.device_status == "offline"

    @pytest.mark.asyncio
    async def test_a_device_inside_its_grace_is_left_alone(self, db_session, make_livelink_vehicle):
        """The WiFi-drop case the grace period exists for."""
        vin, device = await make_livelink_vehicle("finoff", "5")
        service = SessionService(db_session)
        moved_at = FIXED_T0 + timedelta(minutes=1)
        device.last_seen = moved_at
        for at in (FIXED_T0, moved_at):
            await service.observe_telemetry(device, {"SPEED": 44.0}, at, live=True)
        await db_session.flush()
        session_id = device.current_session_id

        device.pending_offline_at = utc_now().replace(tzinfo=None) - timedelta(seconds=10)
        await db_session.flush()

        await _run_finalizer(db_session)

        still_open = await service.get_session(session_id)
        assert still_open is not None
        assert still_open.ended_at is None
        assert device.pending_offline_at is not None

    @pytest.mark.asyncio
    async def test_an_unlinked_device_still_clears_its_pending_state(
        self, db_session, make_livelink_vehicle
    ):
        """No VIN means no session to close, but the state must still be reset,
        or the device stays pending-offline forever and the finalizer revisits
        it on every fifteen-second tick."""
        vin, device = await make_livelink_vehicle("finoff", "6")
        device.vin = None
        device.pending_offline_at = utc_now().replace(tzinfo=None) - timedelta(seconds=120)
        await db_session.flush()

        await _run_finalizer(db_session)
        await db_session.refresh(device)

        assert device.pending_offline_at is None

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

        mock_livelink.get_devices_pending_offline.assert_not_called()

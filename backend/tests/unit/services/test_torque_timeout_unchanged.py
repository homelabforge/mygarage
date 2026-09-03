"""A Torque device's timeout behaviour is byte-identical before and after. C8.

`check_session_timeouts` has no `kind` filter, and the new drive-gap clock reads
`last_movement_at` / `movement_ended_at` / `movement_started_at`. A Torque
session has NONE of those: `resolve_torque_session` never calls the movement
observer, deliberately, because the phone supplies an authoritative session id
and a movement predicate has nothing to add.

So the fallback chain lands on `started_at`, and the gap clock would then close
an actively-uploading Torque trip fifteen minutes after it BEGAN. That is not a
subtle regression: a one-hour drive would be cut into a fifteen-minute session
plus forty-five minutes attributed to nothing, on a source that was working
correctly and that this whole change was supposed to leave alone.

The old rule is the whole rule for Torque: close on contact loss, measured from
`last_seen`, which `resolve_torque_session` stamps on every upload.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.services.session_service import SessionService

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 9, 1, 8, 0, 0)
GAP = 15
TIMEOUT = 5


async def _session_row(db: AsyncSession, session_id: int) -> DriveSession:
    return (
        await db.execute(select(DriveSession).where(DriveSession.id == session_id))
    ).scalar_one()


class TestTorqueTimeouts:
    async def test_an_uploading_trip_is_not_closed_by_the_drive_gap(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """The regression the fallback chain would cause.

        Forty minutes into a drive, phone still uploading. Under the drive gap
        this session's only movement anchor is `started_at`, forty minutes ago,
        so it would be closed mid-trip.
        """
        vin, device = await make_livelink_vehicle("tqto", "1", kind="torque")
        service = SessionService(db_session)

        session = await service.resolve_torque_session(device, "phone-1", T0)
        await db_session.flush()
        assert session is not None
        session_id = session.id

        # The phone is still uploading: `resolve_torque_session` stamps
        # `last_seen` on every packet.
        now = T0 + timedelta(minutes=40)
        device.last_seen = now
        await db_session.flush()

        await service.check_session_timeouts(
            timeout_minutes=TIMEOUT, gap_minutes=GAP, now=now
        )
        await db_session.flush()

        assert (await _session_row(db_session, session_id)).ended_at is None, (
            "the drive gap closed an actively-uploading Torque trip; its "
            "boundaries come from the phone, not from this algorithm"
        )

    async def test_it_is_still_closed_on_contact_loss(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """The paired control. Without it the test above is satisfied by a
        Torque session that no clock can ever close, which leaks open forever
        and blocks every later session through the open-session index."""
        vin, device = await make_livelink_vehicle("tqto", "2", kind="torque")
        service = SessionService(db_session)

        session = await service.resolve_torque_session(device, "phone-2", T0)
        await db_session.flush()
        assert session is not None
        session_id = session.id

        device.last_seen = T0 + timedelta(minutes=1)
        await db_session.flush()

        await service.check_session_timeouts(
            timeout_minutes=TIMEOUT, gap_minutes=GAP, now=T0 + timedelta(minutes=20)
        )
        await db_session.flush()

        assert (await _session_row(db_session, session_id)).ended_at is not None

    async def test_contact_loss_closes_it_at_the_last_contact(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Not at a movement timestamp it does not have.

        A WiCAN session closes at its last MOVEMENT, so the tail of parked
        heartbeats is trimmed. A Torque session has no movement record at all,
        and `last_seen` is the best evidence of when the trip ended -- which is
        exactly what the old rule used.
        """
        vin, device = await make_livelink_vehicle("tqto", "3", kind="torque")
        service = SessionService(db_session)

        session = await service.resolve_torque_session(device, "phone-3", T0)
        await db_session.flush()
        session_id = session.id

        last_upload = T0 + timedelta(minutes=12)
        device.last_seen = last_upload
        await db_session.flush()

        await service.check_session_timeouts(
            timeout_minutes=TIMEOUT, gap_minutes=GAP, now=T0 + timedelta(minutes=30)
        )
        await db_session.flush()

        assert (await _session_row(db_session, session_id)).ended_at == last_upload

    async def test_a_wican_session_is_still_cut_by_the_drive_gap(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """The control on the exemption.

        Whatever distinguishes Torque here must not accidentally exempt WiCAN
        too, which would restore the phantom sessions this release removes.
        """
        vin, device = await make_livelink_vehicle("tqto", "4")
        service = SessionService(db_session)

        moved_at = T0 + timedelta(minutes=1)
        for at in (T0, moved_at):
            device.last_seen = at
            await service.observe_telemetry(device, {"SPEED": 48.0}, at, live=True)
        await db_session.flush()
        session_id = device.current_session_id
        assert session_id is not None

        # Still connected, stationary for twenty minutes.
        now = T0 + timedelta(minutes=21)
        device.last_seen = now
        await db_session.flush()

        await service.check_session_timeouts(
            timeout_minutes=TIMEOUT, gap_minutes=GAP, now=now
        )
        await db_session.flush()

        assert (await _session_row(db_session, session_id)).ended_at == moved_at

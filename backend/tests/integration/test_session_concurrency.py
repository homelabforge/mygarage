"""Two concurrent first-movement payloads create ONE session, not two.

MQTT and HTTPS ingest can genuinely race: both read `livelink_devices.
current_session_id`, both find NULL, and both create. One wins the pointer and
the other is orphaned OPEN forever -- and an open session is never closed by any
later path, because every closing clock starts from the pointer.

Two mechanisms stop it, and they are load-bearing in different ways:

- a **row lock** on the device through session creation, so the common case
  serialises rather than racing;
- the **partial unique index** `uq_drive_sessions_open_per_device`, which makes
  it a constraint rather than a convention.

Lives in `tests/integration/` deliberately. This is one of the two paths CI runs
under PostgreSQL (`pg-migrations-pytest-path: "tests/migrations/
tests/integration/"`), and PostgreSQL is where both mechanisms actually
function: `SELECT ... FOR UPDATE` is a no-op under SQLite's single writer, so a
SQLite-only run would exercise neither and pass regardless.

It needs two real connections, so it builds its own sessions rather than using
the shared `db_session` fixture -- one session cannot race itself.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models.drive_session import DriveSession
from app.models.livelink_device import LiveLinkDevice
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.session_service import SessionService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

T0 = datetime(2026, 9, 1, 8, 0, 0)
MOVING = {"SPEED": 48.0, "ENGINE_RPM": 2100.0}


async def _seed(db_session, prefix: str) -> tuple[str, str]:
    """A committed user/vehicle/device the concurrent sessions can both see."""
    user = User(
        username=f"{prefix}_user",
        email=f"{prefix}@example.com",
        hashed_password="x",
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.flush()

    vin = f"{prefix.upper()}00000000000"[:17]
    db_session.add(Vehicle(vin=vin, user_id=user.id, nickname=prefix, vehicle_type="Car"))
    await db_session.flush()

    device_id = f"{prefix}dev"[:20]
    db_session.add(
        LiveLinkDevice(device_id=device_id, vin=vin, enabled=True, kind="wican", last_seen=T0)
    )
    await db_session.commit()
    return vin, device_id


async def _confirm_movement(sessionmaker, device_id: str, at: datetime) -> None:
    """One ingest path's worth of work, in its own transaction.

    Both above-floor samples are fed here so the debounce is satisfied inside
    this transaction -- the race being tested is over CREATION, and splitting
    the debounce across the two racers would just serialise them by accident.
    """
    async with sessionmaker() as db:
        device = (
            await db.execute(select(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id))
        ).scalar_one()
        service = SessionService(db)
        await service.observe_telemetry(device, MOVING, at, live=True)
        await service.observe_telemetry(device, MOVING, at + timedelta(seconds=30), live=True)
        await db.commit()


class TestConcurrentFirstMovement:
    async def test_two_racing_payloads_leave_one_open_session(self, db_session, test_sessionmaker):
        vin, device_id = await _seed(db_session, "conc1")

        # Both racers run against the same device, from separate connections.
        # One of the two may lose on the constraint; that is the mechanism
        # working, so the exception is captured rather than failing the test.
        results = await asyncio.gather(
            _confirm_movement(test_sessionmaker, device_id, T0),
            _confirm_movement(test_sessionmaker, device_id, T0 + timedelta(seconds=1)),
            return_exceptions=True,
        )

        async with test_sessionmaker() as db:
            open_count = (
                await db.execute(
                    select(func.count(DriveSession.id))
                    .where(DriveSession.device_id == device_id)
                    .where(DriveSession.ended_at.is_(None))
                )
            ).scalar()
            total = (
                await db.execute(
                    select(func.count(DriveSession.id)).where(DriveSession.device_id == device_id)
                )
            ).scalar()

        # NEITHER racer may raise. This is what the row lock buys, and without
        # it the assertion fails while every other assertion here still passes:
        # the index keeps the DATA correct (one open session) while the losing
        # payload takes an IntegrityError, which for a WiCAN is a dropped
        # reading. Measured -- the first version of the lock did not re-read the
        # pointer under it, so the loser's identity-mapped device still held a
        # stale NULL and it created anyway.
        raised = [r for r in results if isinstance(r, BaseException)]
        assert raised == [], (
            f"a racing ingest payload failed instead of adopting the session "
            f"the other one opened: {raised}"
        )

        assert open_count == 1, (
            f"{open_count} open sessions for one device. A second open session is "
            f"orphaned forever: every closing clock starts from the device pointer, "
            f"which only one of them holds. Racer outcomes: {results}"
        )
        assert total == 1, (
            f"{total} sessions created for one drive; both racers wrote. Racer outcomes: {results}"
        )

    async def test_the_pointer_names_the_surviving_session(self, db_session, test_sessionmaker):
        """An open session the pointer does NOT name is the orphan case.

        Counting open sessions alone would pass if the winner's row survived
        while the pointer pointed at the loser's rolled-back id.
        """
        vin, device_id = await _seed(db_session, "conc2")

        await asyncio.gather(
            _confirm_movement(test_sessionmaker, device_id, T0),
            _confirm_movement(test_sessionmaker, device_id, T0 + timedelta(seconds=1)),
            return_exceptions=True,
        )

        async with test_sessionmaker() as db:
            device = (
                await db.execute(
                    select(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id)
                )
            ).scalar_one()
            open_session = (
                await db.execute(
                    select(DriveSession)
                    .where(DriveSession.device_id == device_id)
                    .where(DriveSession.ended_at.is_(None))
                )
            ).scalar_one_or_none()

        assert open_session is not None
        assert device.current_session_id == open_session.id

"""Shared seeding for LiveLink service tests.

The suite shares one database with no per-test rollback, so every test needs
its own User / Vehicle / LiveLinkDevice under identifiers nothing else uses.
That produced the same twenty-eight-line block in four files, each with its own
prefix scheme, and they had already drifted (naive vs aware timestamps). One
factory, parameterised by prefix.
"""

from datetime import timedelta

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.livelink_device import LiveLinkDevice
from app.models.user import User
from app.models.vehicle import Vehicle
from app.utils.datetime_utils import utc_now


@pytest_asyncio.fixture
async def make_livelink_vehicle(db_session: AsyncSession):
    """Async factory: (prefix, suffix, **device_kwargs) -> (vin, device).

    `prefix` scopes the identifiers to the calling module; `suffix`
    distinguishes vehicles within one test.
    """

    async def _factory(prefix: str, suffix: str, **device_kwargs) -> tuple[str, LiveLinkDevice]:
        user = User(
            username=f"{prefix}_user_{suffix}",
            email=f"{prefix}_{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_admin=False,
        )
        db_session.add(user)
        await db_session.flush()

        vin = f"{prefix.upper()}{suffix:0>6}"[-17:]
        db_session.add(
            Vehicle(vin=vin, user_id=user.id, nickname=f"{prefix} {suffix}", vehicle_type="Car")
        )
        await db_session.flush()

        device_kwargs.setdefault("kind", "wican")
        device = LiveLinkDevice(
            device_id=f"{prefix}dev{suffix:0>4}"[-20:], vin=vin, enabled=True, **device_kwargs
        )
        db_session.add(device)
        await db_session.flush()
        return vin, device

    return _factory


@pytest_asyncio.fixture
async def make_closed_drive_session(db_session: AsyncSession, make_livelink_vehicle):
    """Async factory: (prefix, suffix, **session_kwargs) -> (vin, device_id, session).

    The session is already closed, with a window in the recent past and stored
    aggregates a recomputation would have to move. `session_kwargs` overrides
    any DriveSession column.
    """

    async def _factory(prefix: str, suffix: str, **session_kwargs) -> tuple[str, str, DriveSession]:
        vin, device = await make_livelink_vehicle(prefix, suffix)
        now = utc_now().replace(tzinfo=None)

        fields: dict = {
            "started_at": now - timedelta(minutes=30),
            "ended_at": now - timedelta(minutes=20),
            "duration_seconds": 600,
            "max_speed": 20.0,
            "avg_speed": 10.0,
        }
        fields.update(session_kwargs)

        session = DriveSession(vin=vin, device_id=device.device_id, **fields)
        db_session.add(session)
        await db_session.flush()
        return vin, device.device_id, session

    return _factory

"""Tests for LocationService.prune_old: retention-based deletion of location_points."""

import itertools
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.location_point import LocationPoint
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.location_service import LocationService
from app.utils.datetime_utils import utc_now

# Module-level counter for unique identifiers across all tests in this file.
_SEQ = itertools.count()


async def _make_vehicle(db_session: AsyncSession) -> str:
    """Create a minimal user + vehicle, return the (unique) vin."""
    n = next(_SEQ)
    user = User(
        username=f"loc_prune_user_{n}",
        email=f"loc_prune_{n}@example.com",
        hashed_password="x",
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.flush()

    vin = f"LOCPRUNETST{n:06d}"  # 17 chars
    vehicle = Vehicle(
        vin=vin,
        user_id=user.id,
        nickname=f"Loc Prune Car {n}",
        vehicle_type="Car",
    )
    db_session.add(vehicle)
    await db_session.flush()
    return vin


@pytest.mark.asyncio
async def test_prune_old_deletes_points_past_retention_keeps_recent(
    db_session: AsyncSession,
):
    """prune_old(90) deletes a point older than 90 days, keeps a point from
    yesterday, and returns the count of rows deleted.
    """
    vin = await _make_vehicle(db_session)
    service = LocationService(db_session)

    old_point = LocationPoint(
        vin=vin,
        drive_session_id=None,
        source="torque",
        timestamp=utc_now() - timedelta(days=100),
        latitude=Decimal("47.600000"),
        longitude=Decimal("-122.300000"),
    )
    recent_point = LocationPoint(
        vin=vin,
        drive_session_id=None,
        source="torque",
        timestamp=utc_now() - timedelta(days=1),
        latitude=Decimal("47.610000"),
        longitude=Decimal("-122.310000"),
    )
    db_session.add_all([old_point, recent_point])
    await db_session.commit()

    deleted_count = await service.prune_old(90)

    assert deleted_count == 1

    remaining = (
        (await db_session.execute(select(LocationPoint).where(LocationPoint.vin == vin)))
        .scalars()
        .all()
    )
    assert len(remaining) == 1
    assert remaining[0].id == recent_point.id

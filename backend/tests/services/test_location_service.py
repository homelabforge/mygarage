"""Tests for LocationService: idempotent GPS breadcrumb writes + trip read-queries."""

import itertools
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.location_point import LocationPoint
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.location_service import LocationService

# Module-level counter for unique identifiers across all tests in this file.
_SEQ = itertools.count()

FIXED_TS = datetime(2026, 7, 17, 12, 0, 0)  # naive UTC


async def _make_vehicle(db_session: AsyncSession) -> tuple[str, str]:
    """Create a minimal user + vehicle, return its unique (vin, device_id).

    The device id used to be the literal `device_id` in every test in this file.
    The suite shares one database with no per-test rollback, so two tests that
    each seeded an OPEN session for `dev1` left two open sessions on one
    device -- which is exactly what `uq_drive_sessions_open_per_device` now
    forbids. Both tests were legitimate; the shared identifier was not.
    """
    n = next(_SEQ)
    user = User(
        username=f"loc_svc_user_{n}",
        email=f"loc_svc_{n}@example.com",
        hashed_password="x",
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.flush()

    vin = f"LOCSVCTEST{n:07d}"  # 17 chars
    vehicle = Vehicle(
        vin=vin,
        user_id=user.id,
        nickname=f"Loc Svc Car {n}",
        vehicle_type="Car",
    )
    db_session.add(vehicle)
    await db_session.flush()
    return vin, f"locsvcdev{n:04d}"


@pytest.mark.asyncio
async def test_record_point_inserts_and_dedups_on_vin_timestamp_source(
    db_session: AsyncSession,
):
    """First record_point inserts one row and returns True; a duplicate
    (vin, timestamp, 'torque') returns False and does not create a second row.
    """
    vin, device_id = await _make_vehicle(db_session)
    service = LocationService(db_session)

    first = await service.record_point(
        vin, device_id, None, FIXED_TS, Decimal("47.620000"), Decimal("-122.350000")
    )
    await db_session.commit()
    assert first is True

    second = await service.record_point(
        vin, device_id, None, FIXED_TS, Decimal("47.620000"), Decimal("-122.350000")
    )
    await db_session.commit()
    assert second is False

    rows = (
        (await db_session.execute(select(LocationPoint).where(LocationPoint.vin == vin)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].source == "torque"


@pytest.mark.asyncio
async def test_get_trips_only_sessions_with_points_correct_counts_newest_first(
    db_session: AsyncSession,
):
    """get_trips excludes sessions with zero location points, reports the right
    point_count per session, and orders newest-first by started_at.
    """
    vin, device_id = await _make_vehicle(db_session)
    service = LocationService(db_session)

    session_old = DriveSession(
        vin=vin,
        device_id=device_id,
        started_at=datetime(2026, 7, 10, 8, 0, 0),
        ended_at=datetime(2026, 7, 10, 8, 30, 0),
        duration_seconds=1800,
        distance_km=12.5,
    )
    session_new = DriveSession(
        vin=vin,
        device_id=device_id,
        started_at=datetime(2026, 7, 15, 8, 0, 0),
        ended_at=datetime(2026, 7, 15, 8, 30, 0),
        duration_seconds=1800,
        distance_km=20.0,
    )
    session_empty = DriveSession(
        vin=vin, device_id=device_id, started_at=datetime(2026, 7, 12, 8, 0, 0)
    )
    db_session.add_all([session_old, session_new, session_empty])
    await db_session.flush()

    # session_old: 2 points
    await service.record_point(
        vin,
        device_id,
        session_old.id,
        datetime(2026, 7, 10, 8, 0, 0),
        Decimal("47.60"),
        Decimal("-122.30"),
    )
    await service.record_point(
        vin,
        device_id,
        session_old.id,
        datetime(2026, 7, 10, 8, 5, 0),
        Decimal("47.61"),
        Decimal("-122.31"),
    )
    # session_new: 3 points
    await service.record_point(
        vin,
        device_id,
        session_new.id,
        datetime(2026, 7, 15, 8, 0, 0),
        Decimal("47.60"),
        Decimal("-122.30"),
    )
    await service.record_point(
        vin,
        device_id,
        session_new.id,
        datetime(2026, 7, 15, 8, 5, 0),
        Decimal("47.61"),
        Decimal("-122.31"),
    )
    await service.record_point(
        vin,
        device_id,
        session_new.id,
        datetime(2026, 7, 15, 8, 10, 0),
        Decimal("47.62"),
        Decimal("-122.32"),
    )
    # session_empty: no points
    await db_session.commit()

    trips = await service.get_trips(vin)

    assert [t["session_id"] for t in trips] == [session_new.id, session_old.id]
    assert trips[0]["point_count"] == 3
    assert trips[1]["point_count"] == 2
    assert trips[0]["started_at"] == session_new.started_at
    assert trips[0]["ended_at"] == session_new.ended_at
    assert trips[0]["duration_seconds"] == session_new.duration_seconds
    assert trips[0]["distance_km"] == session_new.distance_km


@pytest.mark.asyncio
async def test_get_trip_points_ordered_by_timestamp_scoped_to_vin(
    db_session: AsyncSession,
):
    """get_trip_points returns a session's points ordered by timestamp ascending,
    regardless of insertion order.
    """
    vin, device_id = await _make_vehicle(db_session)
    service = LocationService(db_session)
    session = DriveSession(vin=vin, device_id=device_id, started_at=datetime(2026, 7, 16, 9, 0, 0))
    db_session.add(session)
    await db_session.flush()

    t1 = datetime(2026, 7, 16, 9, 0, 0)
    t2 = datetime(2026, 7, 16, 9, 5, 0)
    t3 = datetime(2026, 7, 16, 9, 10, 0)
    # insert out of chronological order
    await service.record_point(vin, device_id, session.id, t3, Decimal("47.62"), Decimal("-122.32"))
    await service.record_point(vin, device_id, session.id, t1, Decimal("47.60"), Decimal("-122.30"))
    await service.record_point(vin, device_id, session.id, t2, Decimal("47.61"), Decimal("-122.31"))
    await db_session.commit()

    points = await service.get_trip_points(vin, session.id)

    assert [p.timestamp for p in points] == [t1, t2, t3]


@pytest.mark.asyncio
async def test_get_last_location_returns_the_newest_point(db_session: AsyncSession):
    """get_last_location returns the most recent point for the vin, and None
    when there are no points at all.
    """
    vin, device_id = await _make_vehicle(db_session)
    service = LocationService(db_session)

    assert await service.get_last_location(vin) is None

    t1 = datetime(2026, 7, 16, 9, 0, 0)
    t2 = datetime(2026, 7, 16, 10, 0, 0)
    await service.record_point(vin, device_id, None, t1, Decimal("47.60"), Decimal("-122.30"))
    await service.record_point(vin, device_id, None, t2, Decimal("47.61"), Decimal("-122.31"))
    await db_session.commit()

    last = await service.get_last_location(vin)

    assert last is not None
    assert last.timestamp == t2


def test_haversine_km_known_points_within_two_percent_of_one_km():
    """Two points offset by the standard published ~111.32 km-per-degree-latitude
    approximation (independent of the implementation's earth-radius constant) land
    within 2% of 1.0 km.
    """
    lat1, lon1 = 47.6062, -122.3321
    dlat = 1.0 / 111.32
    lat2, lon2 = lat1 + dlat, lon1

    result = LocationService.haversine_km([(lat1, lon1), (lat2, lon2)])

    assert abs(float(result) - 1.0) / 1.0 <= 0.02


def test_haversine_km_empty_or_single_point_returns_zero():
    """An empty list or a single point has no consecutive pair to measure -> 0."""
    assert LocationService.haversine_km([]) == Decimal("0")
    assert LocationService.haversine_km([(47.6062, -122.3321)]) == Decimal("0")

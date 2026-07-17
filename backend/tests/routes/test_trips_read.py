"""Route tests for Task 10: vin-scoped trips + last-location read routes, plus
the location-tracking opt-out PATCH (R1-H4), on the existing
``app/routes/livelink_vehicle.py`` router (prefix
``/api/vehicles/{vin}/livelink``).

Covers:
- GET  .../trips                  -> TripListResponse
- GET  .../trips/{session_id}/points -> TripPointsResponse (ordered, float coords)
- GET  .../location/last          -> LastLocationResponse | null
- PATCH .../location-tracking     -> write-share gated (R1-H4)
- The read gate (``verify_vehicle_access``) is reachable: a user with no
  relationship to the vehicle gets 403 on /trips.

Fixtures: ``client`` / ``db_session`` from tests/conftest.py (base conftest).
Non-admin users are created locally (mirrors test_torque_ingest.py /
test_location_service.py) so JWT auth actually enforces vehicle-access
permissions -- the base conftest's ``test_user`` is an admin, which bypasses
the checks these tests exist to prove.
"""

import itertools
from datetime import datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_share import VehicleShare
from app.services.auth import create_access_token
from app.services.location_service import LocationService

# Module-level counter for unique identifiers across all tests in this file.
_SEQ = itertools.count()


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(data={"sub": str(user.id), "username": user.username})
    return {"Authorization": f"Bearer {token}"}


async def _make_owned_vehicle(db_session: AsyncSession) -> tuple[str, dict[str, str]]:
    """Create a non-admin owner user + vehicle, return (vin, owner_headers)."""
    n = next(_SEQ)
    owner = User(
        username=f"trips_owner_{n}",
        email=f"trips_owner_{n}@example.com",
        hashed_password="x",
        is_active=True,
        is_admin=False,
    )
    db_session.add(owner)
    await db_session.flush()

    vin = f"TRIPREADTEST{n:05d}"  # 17 chars
    vehicle = Vehicle(
        vin=vin,
        user_id=owner.id,
        nickname=f"Trips Read Car {n}",
        vehicle_type="Car",
    )
    db_session.add(vehicle)
    await db_session.commit()

    return vin, _headers(owner)


async def _make_unrelated_headers(db_session: AsyncSession) -> dict[str, str]:
    """Create a non-admin user with no relationship to any test vehicle."""
    n = next(_SEQ)
    user = User(
        username=f"trips_unrelated_{n}",
        email=f"trips_unrelated_{n}@example.com",
        hashed_password="x",
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.commit()

    return _headers(user)


async def _make_vehicle_with_shares(
    db_session: AsyncSession,
) -> tuple[str, dict[str, str], dict[str, str]]:
    """Create an owner + vehicle + a write-share user + a read-only-share user.

    Returns (vin, write_headers, read_headers).
    """
    n = next(_SEQ)
    owner = User(
        username=f"trips_share_owner_{n}",
        email=f"trips_share_owner_{n}@example.com",
        hashed_password="x",
        is_active=True,
        is_admin=False,
    )
    writer = User(
        username=f"trips_writer_{n}",
        email=f"trips_writer_{n}@example.com",
        hashed_password="x",
        is_active=True,
        is_admin=False,
    )
    reader = User(
        username=f"trips_reader_{n}",
        email=f"trips_reader_{n}@example.com",
        hashed_password="x",
        is_active=True,
        is_admin=False,
    )
    db_session.add_all([owner, writer, reader])
    await db_session.flush()

    vin = f"TRIPSHARETST{n:05d}"  # 17 chars
    vehicle = Vehicle(
        vin=vin,
        user_id=owner.id,
        nickname=f"Trips Share Car {n}",
        vehicle_type="Car",
    )
    db_session.add(vehicle)
    await db_session.flush()

    db_session.add_all(
        [
            VehicleShare(
                vehicle_vin=vin, user_id=writer.id, permission="write", shared_by=owner.id
            ),
            VehicleShare(vehicle_vin=vin, user_id=reader.id, permission="read", shared_by=owner.id),
        ]
    )
    await db_session.commit()

    return vin, _headers(writer), _headers(reader)


async def _seed_trip(db_session: AsyncSession, vin: str) -> tuple[int, datetime, datetime]:
    """Create a DriveSession with 2 out-of-order location points.

    Returns (session_id, earlier_timestamp, later_timestamp).
    """
    session = DriveSession(
        vin=vin,
        device_id="dev1",
        started_at=datetime(2026, 7, 16, 9, 0, 0),
        ended_at=datetime(2026, 7, 16, 9, 30, 0),
        duration_seconds=1800,
        distance_km=5.0,
    )
    db_session.add(session)
    await db_session.flush()

    t1 = datetime(2026, 7, 16, 9, 0, 0)
    t2 = datetime(2026, 7, 16, 9, 5, 0)
    service = LocationService(db_session)
    # Inserted out of chronological order to prove the /points route sorts.
    await service.record_point(
        vin, "dev1", session.id, t2, Decimal("47.6070"), Decimal("-122.3315")
    )
    await service.record_point(
        vin, "dev1", session.id, t1, Decimal("47.6062"), Decimal("-122.3321")
    )
    await db_session.commit()

    return session.id, t1, t2


@pytest.mark.asyncio
async def test_get_trips_returns_one_trip_with_correct_point_count(
    client: AsyncClient, db_session: AsyncSession
):
    """GET /trips: 200, one trip, point_count == 2."""
    vin, owner_headers = await _make_owned_vehicle(db_session)
    session_id, _t1, _t2 = await _seed_trip(db_session, vin)

    r = await client.get(f"/api/vehicles/{vin}/livelink/trips", headers=owner_headers)

    assert r.status_code == 200
    body = r.json()
    assert len(body["trips"]) == 1
    trip = body["trips"][0]
    assert trip["session_id"] == session_id
    assert trip["point_count"] == 2


@pytest.mark.asyncio
async def test_get_trip_points_ordered_with_float_coordinates(
    client: AsyncClient, db_session: AsyncSession
):
    """GET /trips/{session_id}/points: 200, 2 points ordered by timestamp
    ascending, lat/lon serialized as numbers (not strings)."""
    vin, owner_headers = await _make_owned_vehicle(db_session)
    session_id, t1, t2 = await _seed_trip(db_session, vin)

    r = await client.get(
        f"/api/vehicles/{vin}/livelink/trips/{session_id}/points", headers=owner_headers
    )

    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == session_id
    points = body["points"]
    assert len(points) == 2

    assert points[0]["timestamp"].startswith(t1.isoformat())
    assert points[1]["timestamp"].startswith(t2.isoformat())

    for p in points:
        assert isinstance(p["latitude"], float)
        assert isinstance(p["longitude"], float)

    assert points[0]["latitude"] == pytest.approx(47.6062)
    assert points[1]["latitude"] == pytest.approx(47.6070)


@pytest.mark.asyncio
async def test_get_trip_points_404s_for_nonexistent_session_id(
    client: AsyncClient, db_session: AsyncSession
):
    """GET /trips/{session_id}/points: 404 (not 200 empty) when the session_id
    doesn't exist at all."""
    vin, owner_headers = await _make_owned_vehicle(db_session)

    r = await client.get(
        f"/api/vehicles/{vin}/livelink/trips/999999999/points", headers=owner_headers
    )

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_trip_points_404s_for_other_vehicles_session_id(
    client: AsyncClient, db_session: AsyncSession
):
    """GET /trips/{session_id}/points: 404 when session_id is real but belongs
    to a DIFFERENT vehicle the caller can access (not the requested vin)."""
    vin_a, owner_headers_a = await _make_owned_vehicle(db_session)
    vin_b, owner_headers_b = await _make_owned_vehicle(db_session)
    session_id_b, _t1, _t2 = await _seed_trip(db_session, vin_b)
    _ = owner_headers_b

    r = await client.get(
        f"/api/vehicles/{vin_a}/livelink/trips/{session_id_b}/points", headers=owner_headers_a
    )

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_last_location_returns_newest_point(
    client: AsyncClient, db_session: AsyncSession
):
    """GET /location/last: 200, the newest point (float coords)."""
    vin, owner_headers = await _make_owned_vehicle(db_session)
    _session_id, t1, t2 = await _seed_trip(db_session, vin)

    r = await client.get(f"/api/vehicles/{vin}/livelink/location/last", headers=owner_headers)

    assert r.status_code == 200
    body = r.json()
    assert body is not None
    assert body["timestamp"].startswith(t2.isoformat())
    assert isinstance(body["latitude"], float)
    assert body["latitude"] == pytest.approx(47.6070)
    _ = t1  # earlier point exists but isn't the "last" one


@pytest.mark.asyncio
async def test_get_last_location_returns_null_when_no_points(
    client: AsyncClient, db_session: AsyncSession
):
    """GET /location/last: 200, null body when the vehicle has no location points."""
    vin, owner_headers = await _make_owned_vehicle(db_session)

    r = await client.get(f"/api/vehicles/{vin}/livelink/location/last", headers=owner_headers)

    assert r.status_code == 200
    assert r.json() is None


@pytest.mark.asyncio
async def test_trips_forbidden_for_user_with_no_vehicle_access(
    client: AsyncClient, db_session: AsyncSession
):
    """GET /trips: a user unrelated to the vehicle gets 403 -- proves the
    verify_vehicle_access read gate is actually wired up."""
    vin, _owner_headers = await _make_owned_vehicle(db_session)
    unrelated_headers = await _make_unrelated_headers(db_session)

    r = await client.get(f"/api/vehicles/{vin}/livelink/trips", headers=unrelated_headers)

    assert r.status_code == 403


@pytest.mark.asyncio
async def test_patch_location_tracking_by_write_share_flips_the_field(
    client: AsyncClient, db_session: AsyncSession
):
    """PATCH /location-tracking as a write-share user: 200, field flipped + persisted."""
    vin, write_headers, _read_headers = await _make_vehicle_with_shares(db_session)

    r = await client.patch(
        f"/api/vehicles/{vin}/livelink/location-tracking",
        json={"enabled": False},
        headers=write_headers,
    )

    assert r.status_code == 200
    assert r.json() == {"location_tracking_enabled": False}

    result = await db_session.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one()
    await db_session.refresh(vehicle)
    assert vehicle.location_tracking_enabled is False


@pytest.mark.asyncio
async def test_patch_location_tracking_by_read_share_is_forbidden(
    client: AsyncClient, db_session: AsyncSession
):
    """PATCH /location-tracking as a read-only-share user: 403 (write gate, R1-H4)."""
    vin, _write_headers, read_headers = await _make_vehicle_with_shares(db_session)

    r = await client.patch(
        f"/api/vehicles/{vin}/livelink/location-tracking",
        json={"enabled": False},
        headers=read_headers,
    )

    assert r.status_code == 403

    result = await db_session.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one()
    await db_session.refresh(vehicle)
    assert vehicle.location_tracking_enabled is True

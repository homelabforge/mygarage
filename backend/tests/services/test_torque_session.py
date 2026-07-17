"""Tests for SessionService.resolve_torque_session: find-or-create DriveSession
resolution for Torque `session` ids (replay/out-of-order safe, server-clock
last_seen). See task-7-brief.md for the codex-review-hardened correctness rules
this encodes (R1-H7, R1-H2, R2-H1, R3-H1).

Also covers Task 11 (GPS-distance fallback at session finalize, task-11-brief.md):
end_session() derives distance_km from the location_points breadcrumb via
LocationService.haversine_km when the odometer path leaves it None.
"""

import itertools
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_telemetry import VehicleTelemetryLatest
from app.services.location_service import LocationService
from app.services.session_service import SessionService
from app.services.torque_service import TorqueService
from app.utils.datetime_utils import utc_now

# Module-level counter for unique identifiers across all tests in this file.
_SEQ = itertools.count()


async def _make_torque_device(db_session: AsyncSession) -> LiveLinkDevice:
    """Create a minimal user + vehicle + kind='torque' device, return the device."""
    n = next(_SEQ)
    user = User(
        username=f"torque_session_user_{n}",
        email=f"torque_session_{n}@example.com",
        hashed_password="x",
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.flush()

    vin = f"TORQSESTEST{n:06d}"  # 17 chars
    vehicle = Vehicle(
        vin=vin,
        user_id=user.id,
        nickname=f"Torque Session Car {n}",
        vehicle_type="Car",
    )
    db_session.add(vehicle)
    await db_session.flush()

    device, _raw_token = await TorqueService(db_session).create_source(vin)
    await db_session.flush()
    return device


@pytest.mark.asyncio
async def test_first_resolve_creates_session_with_server_clock_last_seen(
    db_session: AsyncSession,
):
    """First resolve() for a new session id creates a DriveSession keyed off the
    device-reported timestamp for started_at, but last_seen is stamped from the
    SERVER clock, never the device-reported timestamp (R1-H7).
    """
    device = await _make_torque_device(db_session)
    t_device = datetime(2020, 1, 1, 0, 0, 0)  # deliberately far in the past
    before = utc_now()

    service = SessionService(db_session)
    session = await service.resolve_torque_session(device, "S1", t_device)

    assert session is not None
    assert session.external_session_id == "S1"
    assert session.started_at == t_device
    assert device.current_session_id == session.id
    assert device.last_seen is not None
    assert device.last_seen != t_device
    assert device.last_seen >= before  # server clock, not the device-reported timestamp


@pytest.mark.asyncio
async def test_replay_of_same_session_id_reuses_the_session(db_session: AsyncSession):
    """A repeat resolve() with the same session id returns the SAME session — no
    duplicate is created (R1-H2 find-or-create).
    """
    device = await _make_torque_device(db_session)
    t = datetime(2026, 1, 1, 10, 0, 0)
    service = SessionService(db_session)

    first = await service.resolve_torque_session(device, "S1", t)
    second = await service.resolve_torque_session(device, "S1", t + timedelta(seconds=5))

    assert second is not None
    assert second.id == first.id
    assert await service.get_session_count(device.vin) == 1


@pytest.mark.asyncio
async def test_new_session_id_finalizes_the_prior_open_session(db_session: AsyncSession):
    """A NEW (never-seen) session id that is chronologically newest finalizes the
    prior open session (no orphan left open) and advances the pointer (R2-H1).
    """
    device = await _make_torque_device(db_session)
    t1 = datetime(2026, 1, 1, 10, 0, 0)
    t2 = datetime(2026, 1, 1, 10, 30, 0)
    service = SessionService(db_session)

    s1 = await service.resolve_torque_session(device, "S1", t1)
    s2 = await service.resolve_torque_session(device, "S2", t2)

    assert s1 is not None
    assert s2 is not None
    await db_session.refresh(s1)
    assert s1.ended_at is not None  # no orphan
    assert s1.duration_seconds is not None
    assert s1.duration_seconds >= 0
    assert device.current_session_id == s2.id
    assert s2.ended_at is None


@pytest.mark.asyncio
async def test_replay_of_older_session_id_does_not_move_pointer_or_end_active(
    db_session: AsyncSession,
):
    """A late packet for a KNOWN older session id must not drag current_session_id
    backward or end the active (newer) trip, and must not duplicate the older
    session (R1-H2 + R2-H1).
    """
    device = await _make_torque_device(db_session)
    t1 = datetime(2026, 1, 1, 10, 0, 0)
    t2 = datetime(2026, 1, 1, 10, 30, 0)
    service = SessionService(db_session)

    s1 = await service.resolve_torque_session(device, "S1", t1)
    s2 = await service.resolve_torque_session(device, "S2", t2)
    assert s1 is not None
    assert s2 is not None

    replay = await service.resolve_torque_session(device, "S1", t1 + timedelta(seconds=10))

    assert replay is not None
    assert replay.id == s1.id
    await db_session.refresh(s2)
    assert s2.ended_at is None  # active trip untouched
    assert device.current_session_id == s2.id  # pointer stays on S2, not dragged back

    assert await service.get_session_count(device.vin) == 2  # no duplicate S1 created


@pytest.mark.asyncio
async def test_none_session_id_returns_open_session_or_none_never_creates(
    db_session: AsyncSession,
):
    """torque_session_id=None (GPS-before-session) returns the device's current open
    session if any, else None. It must never create a session.
    """
    device = await _make_torque_device(db_session)
    service = SessionService(db_session)

    # No open session yet -> None, and no session created.
    result = await service.resolve_torque_session(device, None, utc_now())
    assert result is None
    assert await service.get_session_count(device.vin) == 0

    # With an open session -> returns it, still no new session created.
    t1 = datetime(2026, 1, 1, 10, 0, 0)
    s1 = await service.resolve_torque_session(device, "S1", t1)
    assert s1 is not None

    result = await service.resolve_torque_session(device, None, t1 + timedelta(seconds=5))
    assert result is not None
    assert result.id == s1.id
    assert await service.get_session_count(device.vin) == 1


@pytest.mark.asyncio
async def test_older_first_seen_session_does_not_finalize_active_trip(
    db_session: AsyncSession,
):
    """A first-seen session id that is chronologically OLDER than the active trip is
    recorded as an already-closed straggler trip; the active (newer) trip and the
    device's current-session pointer are left untouched (R3-H1).
    """
    device = await _make_torque_device(db_session)
    t0 = datetime(2026, 1, 1, 9, 0, 0)  # older straggler, arrives late
    t2 = datetime(2026, 1, 1, 10, 0, 0)  # active/newest

    service = SessionService(db_session)
    s2 = await service.resolve_torque_session(device, "S2", t2)
    assert s2 is not None

    s0 = await service.resolve_torque_session(device, "S0", t0)
    assert s0 is not None

    await db_session.refresh(s2)
    assert s2.ended_at is None  # active newer trip NOT finalized
    assert device.current_session_id == s2.id  # pointer NOT unseated

    assert s0.id != s2.id
    assert s0.external_session_id == "S0"
    assert s0.started_at == t0
    assert s0.ended_at == t0  # recorded already-closed
    assert s0.duration_seconds == 0

    assert await service.get_session_count(device.vin) == 2


# =============================================================================
# Task 11: GPS-distance fallback at session finalize
# =============================================================================


@pytest.mark.asyncio
async def test_end_session_derives_distance_from_gps_when_no_odometer(
    db_session: AsyncSession,
):
    """A Torque session with no odometer telemetry but >=2 location points spanning
    ~2 km gets distance_km populated from the GPS breadcrumb (within 5% of 2.0).
    """
    device = await _make_torque_device(db_session)
    t0 = datetime(2026, 1, 1, 10, 0, 0)
    service = SessionService(db_session)
    location_service = LocationService(db_session)

    session = await service.resolve_torque_session(device, "S1", t0)
    assert session is not None
    assert session.start_odometer is None  # no telemetry -> no odometer

    # 3 points, ~1 km apart consecutively (~111.32 km per degree latitude) -> ~2 km total.
    lat0, lon0 = 47.6062, -122.3321
    dlat = 1.0 / 111.32
    points = [
        (t0, lat0, lon0),
        (t0 + timedelta(minutes=1), lat0 + dlat, lon0),
        (t0 + timedelta(minutes=2), lat0 + 2 * dlat, lon0),
    ]
    for ts, lat, lon in points:
        await location_service.record_point(
            device.vin, device.device_id, session.id, ts, Decimal(str(lat)), Decimal(str(lon))
        )

    ended = await service.end_session(device, t0 + timedelta(minutes=3))

    assert ended is not None
    assert ended.distance_km is not None
    assert abs(ended.distance_km - 2.0) / 2.0 <= 0.05


@pytest.mark.asyncio
async def test_end_session_odometer_distance_is_not_overridden_by_gps(
    db_session: AsyncSession,
):
    """When both start+end odometer readings are present, distance_km is the
    odometer delta — the GPS fallback must NOT override it, even when location
    points exist and would compute to a very different distance.

    Uses the WiCAN start_session()/end_session() path (not resolve_torque_session):
    a Torque session deliberately never captures start_odometer (see
    test_torque_resolve_never_uses_colocated_wican_odometer below), so the
    odometer-delta-wins-over-GPS behavior this test targets can only occur for a
    device using the WiCAN path, where VIN-scoped odometer capture is correct.
    """
    device = await _make_torque_device(db_session)
    t0 = datetime(2026, 1, 1, 10, 0, 0)

    # Seed the "start" odometer reading before the session opens.
    odo = VehicleTelemetryLatest(vin=device.vin, param_key="ODOMETER", value=1000.0, timestamp=t0)
    db_session.add(odo)
    await db_session.flush()

    service = SessionService(db_session)
    location_service = LocationService(db_session)
    session = await service.start_session(device, t0)
    assert session is not None
    assert session.start_odometer == 1000.0

    # GPS breadcrumb that would compute to ~2 km via haversine if the fallback ran.
    lat0, lon0 = 47.6062, -122.3321
    dlat = 1.0 / 111.32
    await location_service.record_point(
        device.vin, device.device_id, session.id, t0, Decimal(str(lat0)), Decimal(str(lon0))
    )
    await location_service.record_point(
        device.vin,
        device.device_id,
        session.id,
        t0 + timedelta(minutes=1),
        Decimal(str(lat0 + dlat)),
        Decimal(str(lon0)),
    )

    # Advance the "end" odometer reading before finalizing.
    odo.value = 1050.0
    await db_session.flush()

    ended = await service.end_session(device, t0 + timedelta(minutes=2))

    assert ended is not None
    assert ended.distance_km == 50.0  # odometer delta, NOT the ~2 km GPS distance


@pytest.mark.asyncio
async def test_end_session_distance_stays_none_with_fewer_than_two_points(
    db_session: AsyncSession,
):
    """A session with no odometer and fewer than 2 location points leaves
    distance_km as None (no consecutive pair to measure).
    """
    device = await _make_torque_device(db_session)
    t0 = datetime(2026, 1, 1, 10, 0, 0)
    service = SessionService(db_session)
    location_service = LocationService(db_session)

    session = await service.resolve_torque_session(device, "S1", t0)
    assert session is not None

    await location_service.record_point(
        device.vin, device.device_id, session.id, t0, Decimal("47.6062"), Decimal("-122.3321")
    )

    ended = await service.end_session(device, t0 + timedelta(minutes=1))

    assert ended is not None
    assert ended.distance_km is None


@pytest.mark.asyncio
async def test_torque_resolve_never_uses_colocated_wican_odometer(
    db_session: AsyncSession,
):
    """A vehicle with BOTH a WiCAN dongle and a Torque source is a supported config.
    resolve_torque_session() must NOT attribute the co-located WiCAN device's
    VIN-scoped odometer to the Torque trip: Torque has no odometer PID, so
    start_odometer must stay None and distance must come from the GPS breadcrumb,
    NOT the (possibly stale/foreign) WiCAN odometer reading.
    """
    device = await _make_torque_device(db_session)
    t0 = datetime(2026, 1, 1, 10, 0, 0)

    # Simulate a co-located WiCAN device's odometer telemetry for the same VIN.
    # Stale on purpose: if this leaked into the Torque session as both start AND
    # end odometer, distance_km would come out 0 (start == end), NOT None -- which
    # would incorrectly suppress the GPS fallback (`if session.distance_km is None`).
    odo = VehicleTelemetryLatest(vin=device.vin, param_key="ODOMETER", value=50000.0, timestamp=t0)
    db_session.add(odo)
    await db_session.flush()

    service = SessionService(db_session)
    location_service = LocationService(db_session)

    session = await service.resolve_torque_session(device, "S1", t0)
    assert session is not None
    assert session.start_odometer is None  # never captured, even though VIN telemetry exists

    # ~2 km GPS breadcrumb, same pattern as the Task 11 GPS-distance test.
    lat0, lon0 = 47.6062, -122.3321
    dlat = 1.0 / 111.32
    points = [
        (t0, lat0, lon0),
        (t0 + timedelta(minutes=1), lat0 + dlat, lon0),
        (t0 + timedelta(minutes=2), lat0 + 2 * dlat, lon0),
    ]
    for ts, lat, lon in points:
        await location_service.record_point(
            device.vin, device.device_id, session.id, ts, Decimal(str(lat)), Decimal(str(lon))
        )

    ended = await service.end_session(device, t0 + timedelta(minutes=3))

    assert ended is not None
    assert ended.distance_km is not None
    assert ended.distance_km != 0.0  # NOT the stale-odometer start==end zero
    assert abs(ended.distance_km - 2.0) / 2.0 <= 0.05  # GPS distance, not the 50000 odometer

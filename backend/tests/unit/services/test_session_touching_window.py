"""A session that starts where its predecessor ended reads its window from
just after that instant (R11, G4-67).

Touching sessions are made on purpose: the live open and SD reconstruction
both clamp a new start to the device's previous close. With both windows
inclusive the shared sample landed in both, so drive 2 took drive 1's top
speed, its closing odometer, and a harsh brake from a stop that straddled the
boundary. One case per window read, so reverting any one of them fails here.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.vehicle_telemetry import VehicleTelemetry
from app.services.session_service import SessionService

T0 = datetime(2026, 9, 2, 8, 0, 0)


async def _pair(
    db: AsyncSession,
    make_livelink_vehicle,
    suffix: str,
    *,
    gap: timedelta = timedelta(0),
) -> tuple[str, str, DriveSession, DriveSession]:
    """Two closed sessions on one device; the second starts `gap` after the first ends."""
    vin, device = await make_livelink_vehicle("touchwin", suffix)
    first = DriveSession(
        vin=vin,
        device_id=device.device_id,
        started_at=T0 - timedelta(minutes=10) - gap,
        ended_at=T0 - gap,
    )
    second = DriveSession(
        vin=vin,
        device_id=device.device_id,
        started_at=T0,
        ended_at=T0 + timedelta(minutes=30),
    )
    db.add_all([first, second])
    await db.flush()
    return vin, device.device_id, first, second


async def _seed(db: AsyncSession, vin: str, device_id: str, *rows: tuple[int, str, float]) -> None:
    """`(second_offset, param_key, value)` history rows around T0."""
    for offset, key, value in rows:
        db.add(
            VehicleTelemetry(
                vin=vin,
                device_id=device_id,
                param_key=key,
                value=value,
                timestamp=T0 + timedelta(seconds=offset),
                received_at=T0,
            )
        )
    await db.flush()


@pytest.mark.asyncio
class TestATouchingSessionSkipsTheSharedInstant:
    async def test_aggregates(self, db_session: AsyncSession, make_livelink_vehicle):
        vin, device_id, _, second = await _pair(db_session, make_livelink_vehicle, "1")
        await _seed(
            db_session,
            vin,
            device_id,
            (0, "SPEED", 40.0),
            (600, "SPEED", 20.0),
            (1200, "SPEED", 25.0),
        )

        await SessionService(db_session).refresh_aggregates(second)

        assert second.max_speed == pytest.approx(25.0)
        assert second.avg_speed == pytest.approx(22.5)

    async def test_driving_insights(self, db_session: AsyncSession, make_livelink_vehicle):
        vin, device_id, _, second = await _pair(db_session, make_livelink_vehicle, "2")
        await _seed(
            db_session, vin, device_id, (0, "SPEED", 40.0), (2, "SPEED", 0.0), (60, "SPEED", 0.0)
        )

        await SessionService(db_session).refresh_aggregates(second)

        assert second.harsh_brake_count == 0

    async def test_distance_source_discovery(self, db_session: AsyncSession, make_livelink_vehicle):
        """The only odometer row is the shared one, so this session has none."""
        vin, device_id, _, second = await _pair(db_session, make_livelink_vehicle, "3")
        await _seed(db_session, vin, device_id, (0, "A6-ODOMETER", 100.0), (600, "SPEED", 20.0))

        await SessionService(db_session).refresh_aggregates(second)

        assert second.start_odometer is None
        assert second.distance_km is None, "one borrowed sample is not a confident 0 km"

    async def test_odometer_window(self, db_session: AsyncSession, make_livelink_vehicle):
        vin, device_id, _, second = await _pair(db_session, make_livelink_vehicle, "4")
        await _seed(
            db_session,
            vin,
            device_id,
            (0, "A6-ODOMETER", 100.0),
            (600, "A6-ODOMETER", 101.0),
            (1200, "A6-ODOMETER", 104.0),
        )

        await SessionService(db_session).refresh_aggregates(second)

        assert second.start_odometer == pytest.approx(101.0)
        assert second.end_odometer == pytest.approx(104.0)
        assert second.distance_km == pytest.approx(3.0)


@pytest.mark.asyncio
class TestEveryOtherWindowStaysInclusive:
    async def test_no_touching_predecessor_counts_its_first_sample(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Regression guard: a predecessor that ends a second early isn't touching."""
        vin, device_id, _, second = await _pair(
            db_session, make_livelink_vehicle, "5", gap=timedelta(seconds=1)
        )
        await _seed(
            db_session,
            vin,
            device_id,
            (0, "SPEED", 40.0),
            (600, "SPEED", 20.0),
            (0, "A6-ODOMETER", 100.0),
            (600, "A6-ODOMETER", 103.0),
        )

        await SessionService(db_session).refresh_aggregates(second)

        assert second.max_speed == pytest.approx(40.0)
        assert second.start_odometer == pytest.approx(100.0)
        assert second.distance_km == pytest.approx(3.0)

    async def test_the_earlier_session_keeps_the_shared_sample(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Regression guard: only the start goes exclusive, never the end."""
        vin, device_id, first, _ = await _pair(db_session, make_livelink_vehicle, "6")
        await _seed(db_session, vin, device_id, (-300, "SPEED", 20.0), (0, "SPEED", 40.0))

        await SessionService(db_session).refresh_aggregates(first)

        assert first.max_speed == pytest.approx(40.0)

    async def test_a_zero_length_session_is_not_its_own_predecessor(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Regression guard: a session that starts and ends at one instant
        still owns the sample there."""
        vin, device = await make_livelink_vehicle("touchwin", "7")
        point = DriveSession(vin=vin, device_id=device.device_id, started_at=T0, ended_at=T0)
        db_session.add(point)
        await db_session.flush()
        await _seed(db_session, vin, device.device_id, (0, "SPEED", 40.0))

        await SessionService(db_session).refresh_aggregates(point)

        assert point.max_speed == pytest.approx(40.0)

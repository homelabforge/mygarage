"""Telemetry that arrives after a session closes must update that session.

A WiCAN only reaches the broker on home WiFi. Off WiFi it buffers readings and
replays them on reconnect, through the ingest path's optional device timestamp,
so a reading taken at 10:48 can land at 11:42.

Session aggregates were computed once, in `end_session`, from whatever had
arrived by then. On Diamond that meant a drive whose only in-range samples were
the ones taken pulling out of the driveway: the session recorded max_speed
20 km/h while the replayed buffer held 85 km/h, and nothing ever revisited it.

The session's own window is the arbiter. A replayed reading whose timestamp
falls inside a closed session belongs to that session, however late it lands.
"""

from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.livelink_device import LiveLinkDevice
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_telemetry import VehicleTelemetry
from app.services.telemetry_service import TelemetryService
from app.utils.datetime_utils import utc_now


@pytest_asyncio.fixture
async def make_closed_session(db_session: AsyncSession):
    """Async factory: (suffix) -> (vin, device_id, session)."""

    async def _factory(suffix: str) -> tuple[str, str, DriveSession]:
        user = User(
            username=f"latetel_user_{suffix}",
            email=f"latetel_{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_admin=False,
        )
        db_session.add(user)
        await db_session.flush()

        vin = f"LATETELTEST{suffix:0>6}"
        db_session.add(
            Vehicle(vin=vin, user_id=user.id, nickname=f"Late Car {suffix}", vehicle_type="Car")
        )
        await db_session.flush()

        device_id = f"latedev{suffix:0>5}"
        db_session.add(LiveLinkDevice(device_id=device_id, vin=vin, enabled=True, kind="wican"))
        await db_session.flush()

        now = utc_now()
        session = DriveSession(
            vin=vin,
            device_id=device_id,
            started_at=now - timedelta(minutes=10),
            ended_at=now - timedelta(minutes=5),
            duration_seconds=300,
            max_speed=20.0,
            avg_speed=10.0,
        )
        db_session.add(session)
        await db_session.flush()

        # A sample inside the window that the stored max_speed (20) does NOT
        # reflect. Without this, a session refreshed BY MISTAKE recomputes to
        # the same numbers and the negative tests below cannot fail: verified
        # by mutation, both survived until this row existed.
        db_session.add(
            VehicleTelemetry(
                vin=vin,
                device_id=device_id,
                param_key="0D-VEHICLESPEED",
                value=50.0,
                timestamp=session.started_at + timedelta(minutes=1),
                received_at=now,
            )
        )
        await db_session.flush()
        return vin, device_id, session

    return _factory


@pytest.mark.asyncio
class TestLateTelemetrySessionRefresh:
    """A replayed reading inside a closed session's window updates it."""

    async def test_replayed_reading_updates_the_closed_session_max_speed(
        self, db_session, make_closed_session
    ):
        """The buffered 85 km/h sample must reach the session it belongs to."""
        vin, device_id, session = await make_closed_session("1")
        inside = session.started_at + timedelta(minutes=2)

        await TelemetryService(db_session).store_telemetry(
            vin=vin,
            device_id=device_id,
            autopid_data={"0D-VEHICLESPEED": 85.0},
            config={},
            timestamp=inside,
        )
        await db_session.flush()
        await db_session.refresh(session)

        assert session.max_speed == 85.0, "late reading never reached the closed session"

    async def test_reading_outside_every_session_changes_nothing(
        self, db_session, make_closed_session
    ):
        """A reading in the gap between sessions must not be adopted by one.

        Sessions end on device connectivity, so there is real telemetry that
        belongs to no session. Attributing it to the nearest one would invent
        a drive the vehicle did not make.
        """
        vin, device_id, session = await make_closed_session("2")
        after = session.ended_at + timedelta(minutes=1)

        await TelemetryService(db_session).store_telemetry(
            vin=vin,
            device_id=device_id,
            autopid_data={"0D-VEHICLESPEED": 200.0},
            config={},
            timestamp=after,
        )
        await db_session.flush()
        await db_session.refresh(session)

        # 20.0 means untouched. A wrongly-matched session would recompute from
        # the 50 km/h sample seeded inside its window and read 50.0.
        assert session.max_speed == 20.0, "a reading outside the window was adopted"

    async def test_another_vehicles_reading_does_not_touch_the_session(
        self, db_session, make_closed_session
    ):
        """Window matching must be scoped by VIN, not by time alone."""
        vin_a, _dev_a, session_a = await make_closed_session("3")
        _vin_b, dev_b, _session_b = await make_closed_session("4")
        inside_a = session_a.started_at + timedelta(minutes=2)

        # Device B reports at a time that falls inside vehicle A's session too.
        await TelemetryService(db_session).store_telemetry(
            vin=_vin_b,
            device_id=dev_b,
            autopid_data={"0D-VEHICLESPEED": 150.0},
            config={},
            timestamp=inside_a,
        )
        await db_session.flush()
        await db_session.refresh(session_a)

        # 20.0 means untouched; a VIN-blind match would recompute A from its own
        # seeded 50 km/h sample and read 50.0.
        assert session_a.max_speed == 20.0, "another vehicle's reading leaked into this session"

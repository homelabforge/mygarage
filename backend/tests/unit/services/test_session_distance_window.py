"""Session distance must measure odometer movement *inside* the session window.

`end_session` used to compute distance as the difference between the vehicle's
newest odometer reading at session end and its newest reading at session start:

    start_odometer = await self._get_current_odometer(vin)   # at start
    session.end_odometer = await self._get_current_odometer(vin)  # at end
    session.distance_km = session.end_odometer - session.start_odometer

`_get_current_odometer` reads `vehicle_telemetry_latest`, which holds the newest
sample regardless of age. Sessions begin and end on device connectivity, not on
the engine, so a vehicle routinely drives while no session is open. All of that
driving lands in the *next* session's start/end difference.

On Diamond a Ram 3500 idling on remote start in the driveway recorded 11 minutes,
max speed 2 km/h, max RPM 984 -- and 14 km of distance, because the odometer had
advanced by 14 between the previous session and this one. Its earlier session
recorded 129 km the same way. Both were physically impossible for their own
window, and the card read "8.7 mi at 1 mph".

The window is the arbiter. Distance is the span of the odometer samples whose
timestamps fall inside the session; driving that happened while no session was
open belongs to no session, and inventing an owner for it is what produced these
numbers. Recovering those drives needs correct session boundaries, not a wider
odometer lookup.
"""

from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.livelink_device import LiveLinkDevice
from app.models.vehicle_telemetry import VehicleTelemetry, VehicleTelemetryLatest
from app.services.session_service import SessionService
from app.utils.datetime_utils import utc_now


@pytest_asyncio.fixture
async def make_vehicle(make_livelink_vehicle):
    """Async factory: (suffix) -> (vin, device). See conftest."""

    async def _factory(suffix: str) -> tuple[str, LiveLinkDevice]:
        return await make_livelink_vehicle("sdist", suffix)

    return _factory


@pytest_asyncio.fixture
async def seed_odometer(db_session: AsyncSession):
    """Async factory: (vin, device_id, [(offset_seconds, value)], anchor) -> None.

    Writes history rows AND the `vehicle_telemetry_latest` row, so the two
    sources can be made to disagree -- which is the whole point here.
    """

    async def _factory(
        vin: str,
        device_id: str,
        samples: list[tuple[int, float]],
        anchor,
        latest_value: float | None = None,
    ) -> None:
        for offset, value in samples:
            db_session.add(
                VehicleTelemetry(
                    vin=vin,
                    device_id=device_id,
                    param_key="A6-ODOMETER",
                    value=value,
                    timestamp=anchor + timedelta(seconds=offset),
                    received_at=anchor,
                )
            )
        if latest_value is not None:
            db_session.add(
                VehicleTelemetryLatest(
                    vin=vin,
                    param_key="A6-ODOMETER",
                    value=latest_value,
                    timestamp=anchor,
                )
            )
        await db_session.flush()

    return _factory


@pytest.mark.asyncio
class TestSessionDistanceWindow:
    """Only odometer movement observed during the session counts."""

    async def test_idle_session_records_no_distance(self, db_session, make_vehicle, seed_odometer):
        """The Ram's driveway idle: odometer flat all session, 14 km inherited.

        The odometer reads 12524 for every in-window sample. The latest-value
        table also says 12524, and the session opened with start_odometer 12510
        carried over from the previous session. Differencing those two gives the
        14 km that the truck did not drive during these 11 minutes.
        """
        vin, device = await make_vehicle("1")
        anchor = utc_now().replace(tzinfo=None) - timedelta(hours=1)

        session = await SessionService(db_session).start_session(device, anchor)
        session.start_odometer = 12510.0  # carried over from the previous session
        await db_session.flush()

        await seed_odometer(
            vin,
            device.device_id,
            [(30, 12524.0), (300, 12524.0), (600, 12524.0)],
            anchor,
            latest_value=12524.0,
        )

        await SessionService(db_session).end_session(device, anchor + timedelta(seconds=660))
        await db_session.flush()

        assert session.distance_km == 0.0, "driving from before the session was attributed to it"
        assert session.start_odometer == 12524.0, "start odometer kept a pre-session value"
        assert session.end_odometer == 12524.0

    async def test_distance_is_the_span_of_in_window_readings(
        self, db_session, make_vehicle, seed_odometer
    ):
        """A real drive: the odometer advances during the session and that counts."""
        vin, device = await make_vehicle("2")
        anchor = utc_now().replace(tzinfo=None) - timedelta(hours=1)

        session = await SessionService(db_session).start_session(device, anchor)
        session.start_odometer = 1000.0  # stale carry-over, must be replaced
        await db_session.flush()

        # Latest-value differencing would give 1120 - 1000 = 120, so 7.0 is
        # only reachable by reading the window.
        await seed_odometer(
            vin,
            device.device_id,
            [(30, 1113.0), (300, 1116.5), (600, 1120.0)],
            anchor,
            latest_value=1120.0,
        )

        await SessionService(db_session).end_session(device, anchor + timedelta(seconds=660))
        await db_session.flush()

        assert session.distance_km == 7.0
        assert session.start_odometer == 1113.0
        assert session.end_odometer == 1120.0

    async def test_readings_outside_the_window_are_excluded(
        self, db_session, make_vehicle, seed_odometer
    ):
        """Samples before the start or after the end belong to other drives.

        The out-of-window rows here are the gap driving: 40 km before the session
        opened and 60 km after it closed. Counting either would make the span
        100.0 instead of 7.0.
        """
        vin, device = await make_vehicle("3")
        anchor = utc_now().replace(tzinfo=None) - timedelta(hours=2)

        session = await SessionService(db_session).start_session(device, anchor)
        await db_session.flush()

        await seed_odometer(
            vin,
            device.device_id,
            [
                (-3600, 1073.0),  # before the session opened
                (30, 1113.0),
                (600, 1120.0),
                (7200, 1180.0),  # after the session closed
            ],
            anchor,
            latest_value=1180.0,
        )

        await SessionService(db_session).end_session(device, anchor + timedelta(seconds=660))
        await db_session.flush()

        assert session.distance_km == 7.0, "an out-of-window reading was counted"

    async def test_another_vehicles_odometer_does_not_count(
        self, db_session, make_vehicle, seed_odometer
    ):
        """Window matching must be scoped by VIN as well as by time."""
        vin_a, device_a = await make_vehicle("4")
        vin_b, device_b = await make_vehicle("5")
        anchor = utc_now().replace(tzinfo=None) - timedelta(hours=1)

        session = await SessionService(db_session).start_session(device_a, anchor)
        await db_session.flush()

        await seed_odometer(
            vin_a, device_a.device_id, [(30, 1113.0), (600, 1120.0)], anchor, latest_value=1120.0
        )
        # Vehicle B drives 500 km over the same wall-clock window.
        await seed_odometer(
            vin_b, device_b.device_id, [(30, 9000.0), (600, 9500.0)], anchor, latest_value=9500.0
        )

        await SessionService(db_session).end_session(device_a, anchor + timedelta(seconds=660))
        await db_session.flush()

        assert session.distance_km == 7.0, "another vehicle's odometer leaked into this session"

    async def test_pruned_telemetry_leaves_the_stored_distance_alone(
        self, db_session, make_vehicle, seed_odometer
    ):
        """No in-window samples must not blank a session summarised long ago.

        Telemetry is pruned on a retention schedule while sessions are kept
        forever, so an old session's window is legitimately empty. This mirrors
        `_calculate_session_aggregates`, which only assigns when it finds rows.
        """
        vin, device = await make_vehicle("6")
        anchor = utc_now().replace(tzinfo=None) - timedelta(hours=1)

        session = await SessionService(db_session).start_session(device, anchor)
        await db_session.flush()
        session.ended_at = anchor + timedelta(seconds=660)
        session.distance_km = 42.0
        await db_session.flush()

        # Only far-outside rows survive; the window itself has been pruned.
        await seed_odometer(vin, device.device_id, [(-86400, 500.0)], anchor, latest_value=500.0)

        await SessionService(db_session).refresh_aggregates(session)
        await db_session.flush()

        assert session.distance_km == 42.0, "an empty window blanked a stored distance"

    async def test_refresh_recomputes_distance_from_late_telemetry(
        self, db_session, make_vehicle, seed_odometer
    ):
        """The repair path must fix distance, not just speed.

        `refresh_aggregates` is what both the late-telemetry hook and the
        history repair tool call. If it recomputes speeds but leaves distance,
        every historical session keeps the number this change exists to fix.
        """
        vin, device = await make_vehicle("7")
        anchor = utc_now().replace(tzinfo=None) - timedelta(hours=1)

        session = await SessionService(db_session).start_session(device, anchor)
        await db_session.flush()
        session.ended_at = anchor + timedelta(seconds=660)
        session.distance_km = 129.0  # the bogus stored value
        await db_session.flush()

        await seed_odometer(
            vin, device.device_id, [(30, 12510.0), (600, 12510.0)], anchor, latest_value=12510.0
        )

        await SessionService(db_session).refresh_aggregates(session)
        await db_session.flush()

        assert session.distance_km == 0.0, "refresh_aggregates left the stale distance in place"


@pytest.mark.asyncio
class TestSessionDistanceDeviceScope:
    """A session's distance comes from its own device, not the VIN's."""

    async def test_a_colocated_wican_odometer_does_not_stamp_a_torque_session(
        self, db_session, make_livelink_vehicle, seed_odometer
    ):
        """One vehicle can carry both a WiCAN dongle and a Torque source.

        `resolve_torque_session` deliberately leaves `start_odometer` unset for
        exactly this case: Torque has no odometer PID, and attributing the
        co-located WiCAN's odometer to a Torque trip lets one device decide
        another device's distance. Measuring the window by VIN alone walked
        straight back through that safeguard, because the WiCAN's samples fall
        in the Torque session's window too.

        Distance for a Torque trip belongs to the GPS breadcrumb, and with no
        breadcrumb here it must stay unset rather than borrow 7 km.
        """
        vin, wican = await make_livelink_vehicle("dvscope", "1")
        torque = LiveLinkDevice(device_id="dvscopetq1", vin=vin, enabled=True, kind="torque")
        db_session.add(torque)
        await db_session.flush()

        anchor = utc_now().replace(tzinfo=None) - timedelta(hours=1)
        session = DriveSession(
            vin=vin,
            device_id=torque.device_id,
            started_at=anchor,
            ended_at=anchor + timedelta(seconds=660),
        )
        db_session.add(session)
        await db_session.flush()

        # The WiCAN reports the vehicle's odometer across the same window.
        await seed_odometer(
            vin, wican.device_id, [(30, 1113.0), (600, 1120.0)], anchor, latest_value=1120.0
        )

        await SessionService(db_session).refresh_aggregates(session)
        await db_session.flush()

        assert session.distance_km is None, (
            "a co-located WiCAN's odometer was attributed to a Torque trip"
        )

    async def test_the_session_still_reads_its_own_devices_odometer(
        self, db_session, make_vehicle, seed_odometer
    ):
        """Scoping by device must not stop a session reading its own samples."""
        vin, device = await make_vehicle("8")
        anchor = utc_now().replace(tzinfo=None) - timedelta(hours=1)

        session = await SessionService(db_session).start_session(device, anchor)
        await db_session.flush()
        await seed_odometer(
            vin, device.device_id, [(30, 1113.0), (600, 1120.0)], anchor, latest_value=1120.0
        )

        await SessionService(db_session).end_session(device, anchor + timedelta(seconds=660))
        await db_session.flush()

        assert session.distance_km == 7.0

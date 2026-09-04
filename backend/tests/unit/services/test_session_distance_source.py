"""A session's distance comes from the finest distance signal in its window.

`_calculate_session_distance` read odometer keys and nothing else, which is
correct on hardware whose odometer resolves finely and useless on hardware whose
odometer steps further than a typical trip. The measurements, and the argument
for which keys qualify, live in `app/utils/distance_counters.py`; the selection
arithmetic is unit-tested without a database in
`tests/unit/utils/test_distance_counters.py`.

What is left to test HERE is the part that needs rows: that the winning source
reaches `distance_km`, that the odometer alone reaches `start_odometer` /
`end_odometer`, and that the session window still bounds every source rather
than only the odometer.
"""

from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.models.vehicle_telemetry import VehicleTelemetry
from app.services.session_service import SessionService
from app.utils.datetime_utils import utc_now


@pytest_asyncio.fixture
async def make_vehicle(make_livelink_vehicle):
    """Async factory: (suffix) -> (vin, device)."""

    async def _factory(suffix: str) -> tuple[str, LiveLinkDevice]:
        return await make_livelink_vehicle("dsrc", suffix)

    return _factory


@pytest_asyncio.fixture
async def seed(db_session: AsyncSession):
    """Async factory: (vin, device_id, param_key, [(offset_s, value)], anchor) -> None."""

    async def _factory(
        vin: str,
        device_id: str,
        param_key: str,
        samples: list[tuple[int, float]],
        anchor,
    ) -> None:
        for offset, value in samples:
            db_session.add(
                VehicleTelemetry(
                    vin=vin,
                    device_id=device_id,
                    param_key=param_key,
                    value=value,
                    timestamp=anchor + timedelta(seconds=offset),
                    received_at=anchor,
                )
            )
        await db_session.flush()

    return _factory


async def _run_session(db_session, device, anchor, seconds: int = 900):
    """Open and close a session over the window, returning the closed row."""
    service = SessionService(db_session)
    await service.start_session(device, anchor)
    await db_session.flush()
    session = await service.end_session(device, anchor + timedelta(seconds=seconds))
    await db_session.flush()
    return session


@pytest.mark.asyncio
class TestDistanceSourceSelection:
    async def test_a_finer_counter_beats_a_flat_odometer(self, db_session, make_vehicle, seed):
        """The Mirage's real shape: the odometer never ticks, the counter does.

        A 12 km drive that the odometer cannot see at all, because its step is
        twice the length of the trip. Reading only the odometer records zero.
        """
        vin, device = await make_vehicle("1")
        anchor = utc_now().replace(tzinfo=None) - timedelta(hours=1)

        await seed(vin, device.device_id, "ODOMETER", [(30, 141300.0), (600, 141300.0)], anchor)
        await seed(
            vin,
            device.device_id,
            "31-DISTANCESINCECODECLEAR",
            [(30, 500.0), (200, 504.0), (400, 509.0), (600, 512.0)],
            anchor,
        )

        session = await _run_session(db_session, device, anchor)

        assert session is not None
        assert session.distance_km == pytest.approx(12.0)

    async def test_a_counter_never_stamps_the_odometer_columns(
        self, db_session, make_vehicle, seed
    ):
        """Distance from the counter, odometer columns untouched.

        PID 0x31 counts from the last code clear, so its value is not mileage.
        Writing 512 into `start_odometer` would report a vehicle with 512 km on
        it, which is a worse lie than a missing number.
        """
        vin, device = await make_vehicle("2")
        anchor = utc_now().replace(tzinfo=None) - timedelta(hours=1)

        await seed(
            vin,
            device.device_id,
            "31-DISTANCESINCECODECLEAR",
            [(30, 500.0), (600, 512.0)],
            anchor,
        )

        session = await _run_session(db_session, device, anchor)

        assert session is not None
        assert session.distance_km == pytest.approx(12.0)
        assert session.start_odometer is None
        assert session.end_odometer is None

    async def test_the_odometer_still_supplies_both_when_it_wins(
        self, db_session, make_vehicle, seed
    ):
        """A device whose odometer resolves finely is completely unaffected.

        The Ram's shape: `A6-ODOMETER` steps about every 2 km, so it out-resolves
        anything else in the window and keeps all three fields.
        """
        vin, device = await make_vehicle("3")
        anchor = utc_now().replace(tzinfo=None) - timedelta(hours=1)

        await seed(
            vin,
            device.device_id,
            "A6-ODOMETER",
            [(30, 9195.0), (200, 9197.0), (400, 9203.0), (600, 9210.0)],
            anchor,
        )
        await seed(
            vin,
            device.device_id,
            "31-DISTANCESINCECODECLEAR",
            [(30, 100.0), (600, 122.0)],
            anchor,
        )

        session = await _run_session(db_session, device, anchor)

        assert session is not None
        assert session.distance_km == pytest.approx(15.0), (
            "the odometer's 15, not the coarser counter's 22 -- the two are "
            "deliberately different so this assertion can tell them apart"
        )
        assert session.start_odometer == pytest.approx(9195.0)
        assert session.end_odometer == pytest.approx(9210.0)

    async def test_an_equal_resolution_tie_goes_to_the_odometer(
        self, db_session, make_vehicle, seed
    ):
        """Displacing the odometer requires resolving STRICTLY finer.

        Both sources step twice here. The odometer keeps the job, so this change
        can only ever add distance to sessions that had none, never quietly
        restate sessions that were already being measured.
        """
        vin, device = await make_vehicle("4")
        anchor = utc_now().replace(tzinfo=None) - timedelta(hours=1)

        await seed(
            vin,
            device.device_id,
            "A6-ODOMETER",
            [(30, 9195.0), (300, 9200.0), (600, 9205.0)],
            anchor,
        )
        await seed(
            vin,
            device.device_id,
            "31-DISTANCESINCECODECLEAR",
            [(30, 100.0), (300, 108.0), (600, 118.0)],
            anchor,
        )

        session = await _run_session(db_session, device, anchor)

        assert session is not None
        assert session.distance_km == pytest.approx(10.0), (
            "the odometer's span, not the counter's 18"
        )

    async def test_a_reset_inside_the_window_sums_only_the_rises(
        self, db_session, make_vehicle, seed
    ):
        """A code clear mid-window must not become 800 km of driving.

        `max - min` over these samples is 806. The vehicle drove 15.
        """
        vin, device = await make_vehicle("5")
        anchor = utc_now().replace(tzinfo=None) - timedelta(hours=1)

        await seed(
            vin,
            device.device_id,
            "31-DISTANCESINCECODECLEAR",
            [(30, 800.0), (200, 810.0), (400, 4.0), (600, 9.0)],
            anchor,
        )

        session = await _run_session(db_session, device, anchor)

        assert session is not None
        assert session.distance_km == pytest.approx(15.0)

    async def test_an_unprefixed_counter_is_not_a_distance_source(
        self, db_session, make_vehicle, seed
    ):
        """A bare autopid of the same name reports the dash, in unknown units.

        Nothing declares units for a distance counter the way
        `LiveLinkDevice.odometer_unit` does for an odometer, so this contributes
        no distance rather than 12 possibly-mile kilometres.
        """
        vin, device = await make_vehicle("6")
        anchor = utc_now().replace(tzinfo=None) - timedelta(hours=1)

        await seed(
            vin,
            device.device_id,
            "DISTANCESINCECODECLEAR",
            [(30, 500.0), (600, 512.0)],
            anchor,
        )

        session = await _run_session(db_session, device, anchor)

        assert session is not None
        assert not session.distance_km, "an unreadable source contributes nothing"

    async def test_samples_outside_the_window_are_still_excluded(
        self, db_session, make_vehicle, seed
    ):
        """The window remains the arbiter for the counter, exactly as for the odometer.

        Driving that happened while no session was open belongs to no session.
        The counter must not reopen the wider-lookup bug the odometer path was
        fixed for.
        """
        vin, device = await make_vehicle("7")
        anchor = utc_now().replace(tzinfo=None) - timedelta(hours=1)

        await seed(
            vin,
            device.device_id,
            "31-DISTANCESINCECODECLEAR",
            [(-3600, 400.0), (30, 500.0), (600, 512.0), (5400, 900.0)],
            anchor,
        )

        session = await _run_session(db_session, device, anchor)

        assert session is not None
        assert session.distance_km == pytest.approx(12.0)

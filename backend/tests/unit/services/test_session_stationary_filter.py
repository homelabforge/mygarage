"""The drive list can hide sessions in which nothing moved.

Sessions used to open whenever the dongle could reach the broker, and a parked
WiCAN checks in about every 95 minutes. On the instance this was built against
**2,921 of 3,262 recorded sessions never moved at all**: no distance, top speed
under the 5 km/h floor. They are not drives, and they are not going to become
drives, because the telemetry needed to rebuild them was never captured
(`app/utils/distance_counters.py`).

Deleting them is not the answer, and an earlier revision of this release shipped
a tool that tried: it removed 2,700 km of real recorded distance and created
nothing. So the list narrows and every row stays where it is.

WHY NOT FILTER ON `boundary_algorithm_version`
----------------------------------------------
Because it is the wrong question, and the first version of this asked it. Of
those 3,262 pre-098 sessions **341 record a vehicle that demonstrably moved**.
Hiding by algorithm buries all 341 along with the noise, and they are the user's
own history of real journeys. What makes a row worthless is that nothing moved,
not which rule cut it.
"""

from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.services.session_service import SessionService
from app.utils.datetime_utils import utc_now


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession, make_livelink_vehicle):
    """A fleet covering every combination the filter has to separate."""
    vin, device = await make_livelink_vehicle("slgcy", "1")
    anchor = utc_now() - timedelta(days=10)
    rows = [
        # Old rule, nothing moved: the parked heartbeat cohort.
        dict(boundary_algorithm_version=0, distance_km=0.0, max_speed=0.0),
        dict(boundary_algorithm_version=0, distance_km=None, max_speed=None),
        dict(boundary_algorithm_version=0, distance_km=0.0, max_speed=2.0),
        # Old rule, but a REAL drive. Must survive the filter.
        dict(boundary_algorithm_version=0, distance_km=12.4, max_speed=64.0),
        dict(boundary_algorithm_version=0, distance_km=0.0, max_speed=48.0),
        # New rule, a real drive.
        dict(boundary_algorithm_version=1, distance_km=8.0, max_speed=55.0),
    ]
    for index, row in enumerate(rows):
        db_session.add(
            DriveSession(
                vin=vin,
                device_id=device.device_id,
                started_at=anchor + timedelta(hours=index),
                ended_at=anchor + timedelta(hours=index, minutes=20),
                **row,
            )
        )
    await db_session.flush()
    return vin, device


@pytest.mark.asyncio
class TestStationarySessionFilter:
    async def test_the_list_includes_everything_by_default(self, db_session, seeded):
        """The default must not silently drop history from an existing caller."""
        vin, _ = seeded

        sessions = await SessionService(db_session).get_vehicle_sessions(vin=vin)

        assert len(sessions) == 6

    async def test_excluding_stationary_keeps_every_drive_that_moved(self, db_session, seeded):
        """Three moved: two under the old rule, one under the new."""
        vin, _ = seeded

        sessions = await SessionService(db_session).get_vehicle_sessions(
            vin=vin, include_stationary=False
        )

        assert len(sessions) == 3

    async def test_a_real_drive_recorded_by_the_old_rule_survives(self, db_session, seeded):
        """The 341, and the reason this does not filter on the algorithm version.

        A pre-098 session that covered 12.4 km at 64 km/h is a journey the user
        took. Hiding it because of HOW it was detected discards real history to
        tidy up a display.
        """
        vin, _ = seeded

        sessions = await SessionService(db_session).get_vehicle_sessions(
            vin=vin, include_stationary=False
        )

        legacy_kept = [s for s in sessions if s.boundary_algorithm_version == 0]
        assert len(legacy_kept) == 2
        assert any(s.distance_km == 12.4 for s in legacy_kept)

    async def test_speed_alone_is_enough_to_keep_a_drive(self, db_session, seeded):
        """A drive whose odometer never ticked still moved.

        This is the whole Mirage cohort: an odometer that steps every 24 km
        reports zero distance for most trips, so requiring distance would hide
        real drives on exactly the hardware this release exists for.
        """
        vin, _ = seeded

        sessions = await SessionService(db_session).get_vehicle_sessions(
            vin=vin, include_stationary=False
        )

        assert any(s.distance_km == 0.0 and s.max_speed == 48.0 for s in sessions)

    async def test_a_null_speed_is_not_evidence_of_movement(self, db_session, seeded):
        """A pruned session cannot prove it was a drive, so it reads as stationary.

        The alternative shows every unprovable row and defeats the filter: on
        the measured data 2,816 sessions have no speed on record and only 5 of
        them carry any distance.
        """
        vin, _ = seeded

        sessions = await SessionService(db_session).get_vehicle_sessions(
            vin=vin, include_stationary=False
        )

        assert not any(s.max_speed is None for s in sessions)

    async def test_the_count_matches_the_filter(self, db_session, seeded):
        """A total counting rows the list refuses to show breaks pagination."""
        vin, _ = seeded
        service = SessionService(db_session)

        assert await service.get_session_count(vin) == 6
        assert await service.get_session_count(vin, include_stationary=False) == 3

    async def test_the_stationary_count_is_available_on_its_own(self, db_session, seeded):
        """So the empty state can say how many drives are being held back."""
        vin, _ = seeded

        assert await SessionService(db_session).get_stationary_session_count(vin) == 3

    async def test_nothing_is_deleted_by_filtering(self, db_session, seeded):
        """The rows stay; only the view narrows."""
        vin, _ = seeded
        service = SessionService(db_session)

        await service.get_vehicle_sessions(vin=vin, include_stationary=False)

        assert await service.get_session_count(vin) == 6

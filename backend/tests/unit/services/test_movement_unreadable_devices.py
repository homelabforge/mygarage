"""Which devices genuinely cannot have their movement read.

The rule, and why asking `last_movement_at IS NULL` alone named entire fleets on
the first boot after migration 098, are argued on
`LiveLinkService.movement_unreadable_device_ids`.

Every test here seeds the state that makes it meaningful: the method's default
answer is "not flagged", so an assertion of absence proves nothing unless the
fixture is one that SHOULD have been flagged but for the single property under
test.
"""

from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.models.vehicle_telemetry import VehicleTelemetry
from app.services.livelink_service import LiveLinkService
from app.utils.datetime_utils import utc_now


@pytest_asyncio.fixture
async def make_vehicle(make_livelink_vehicle):
    async def _factory(suffix: str) -> tuple[str, LiveLinkDevice]:
        return await make_livelink_vehicle("munr", suffix)

    return _factory


@pytest_asyncio.fixture
async def seed(db_session: AsyncSession):
    """Async factory: (vin, device_id, [(param_key, age_days)]) -> None."""

    async def _factory(vin: str, device_id: str, samples: list[tuple[str, float]]) -> None:
        now = utc_now()
        for param_key, age_days in samples:
            db_session.add(
                VehicleTelemetry(
                    vin=vin,
                    device_id=device_id,
                    param_key=param_key,
                    value=1.0,
                    timestamp=now - timedelta(days=age_days),
                    received_at=now - timedelta(days=age_days),
                )
            )
        await db_session.flush()

    return _factory


@pytest.mark.asyncio
class TestMovementUnreadableDeviceIds:
    async def test_engine_telemetry_without_movement_is_flagged(
        self, db_session, make_vehicle, seed
    ):
        """The actionable case: plainly running, and nothing here can read it."""
        vin, device = await make_vehicle("1")
        await seed(vin, device.device_id, [("0C-ENGINERPM", 1), ("CUSTOM_ROAD_SPEED", 1)])

        flagged = await LiveLinkService(db_session).movement_unreadable_device_ids([device])

        assert device.device_id in flagged

    async def test_legible_rpm_does_not_make_a_device_readable(
        self, db_session, make_vehicle, seed
    ):
        """RPM is a movement signal and still does not answer this question.

        An engine turning with the vehicle stationary is a remote start, a
        warm-up or a driveway idle, so RPM opens a PENDING drive and never
        confirms one. A device whose RPM is perfectly legible but whose speed
        arrives under an unrecognised name records no sessions at all, which is
        exactly the cohort this names. Counting RPM as readable would hide it.
        """
        vin, device = await make_vehicle("10")
        await seed(vin, device.device_id, [("0C-ENGINERPM", 1), ("CUSTOM_ROAD_SPEED", 1)])

        flagged = await LiveLinkService(db_session).movement_unreadable_device_ids([device])

        assert device.device_id in flagged

    async def test_a_parked_heartbeat_alone_is_not_flagged(self, db_session, make_vehicle, seed):
        """The day-one false alarm, and the reason this is not `last_movement_at IS NULL`.

        Right after the upgrade every device has no movement on record. One that
        has published nothing but its battery heartbeat since is a parked
        vehicle behaving correctly, and naming it would fire the warning for an
        entire fleet on first boot.
        """
        vin, device = await make_vehicle("2")
        await seed(vin, device.device_id, [("BATTERY_VOLTAGE", 0.5), ("BATTERY_VOLTAGE", 2)])

        flagged = await LiveLinkService(db_session).movement_unreadable_device_ids([device])

        assert device.device_id not in flagged

    async def test_a_readable_device_is_not_flagged_before_it_has_moved(
        self, db_session, make_vehicle, seed
    ):
        """The day migration 098 runs, and the bug that survived the first fix.

        `last_movement_at` is a column 098 CREATES, so it is null for every
        device that exists until fresh telemetry arrives. Pairing that against
        seven days of telemetry HISTORY compares two different time bases: the
        history is almost entirely older than the column. Every device driven in
        the last week but not since the upgrade came out flagged, which on a
        real database was the entire fleet.

        So the question is asked without reference to time at all. This device
        publishes `0D-VEHICLESPEED`, which this codebase reads; whether it has
        moved YET is a different question and not the one the notice answers.
        """
        vin, device = await make_vehicle("3")
        assert device.last_movement_at is None, "as 098 leaves every existing device"
        await seed(
            vin,
            device.device_id,
            [("0C-ENGINERPM", 1), ("0D-VEHICLESPEED", 1), ("05-ENGINECOOLANTTEMP", 1)],
        )

        flagged = await LiveLinkService(db_session).movement_unreadable_device_ids([device])

        assert device.device_id not in flagged

    async def test_an_unprefixed_odometer_alone_counts_as_readable(
        self, db_session, make_vehicle, seed
    ):
        """The cohort with no recognised speed key still has a readable odometer.

        An odometer increase is one of the three movement proofs, so a device
        reporting a bare `ODOMETER` autopid and nothing else recognisable is
        readable and must not be named.
        """
        vin, device = await make_vehicle("9")
        await seed(vin, device.device_id, [("0C-ENGINERPM", 1), ("ODOMETER", 1)])

        flagged = await LiveLinkService(db_session).movement_unreadable_device_ids([device])

        assert device.device_id not in flagged

    async def test_a_disabled_device_is_not_flagged(self, db_session, make_vehicle, seed):
        """Nothing is expected of it, so nothing is wrong with it."""
        vin, device = await make_vehicle("4")
        device.enabled = False
        await db_session.flush()
        await seed(vin, device.device_id, [("0C-ENGINERPM", 1)])

        flagged = await LiveLinkService(db_session).movement_unreadable_device_ids([device])

        assert device.device_id not in flagged

    async def test_a_device_quiet_for_longer_than_the_window_is_not_flagged(
        self, db_session, make_vehicle, seed
    ):
        """A dongle in a drawer is not a misconfiguration to act on.

        Its `last_seen` is stale, which is the cheap half of the test: it is
        excluded before any query runs.
        """
        vin, device = await make_vehicle("5")
        device.last_seen = utc_now() - timedelta(days=60)
        await db_session.flush()
        await seed(vin, device.device_id, [("0C-ENGINERPM", 60)])

        flagged = await LiveLinkService(db_session).movement_unreadable_device_ids([device])

        assert device.device_id not in flagged

    async def test_a_never_seen_device_is_still_asked_about(self, db_session, make_vehicle, seed):
        """An unset `last_seen` is not proof of an unused device.

        SD-card backfill inserts telemetry without going through
        `store_telemetry`, so a dongle that only ever delivers off the card has
        engine telemetry on record and no `last_seen` at all. Excluding it as
        dormant would hide exactly the away-from-home cohort.
        """
        vin, device = await make_vehicle("8")
        assert device.last_seen is None
        await seed(vin, device.device_id, [("0C-ENGINERPM", 1)])

        flagged = await LiveLinkService(db_session).movement_unreadable_device_ids([device])

        assert device.device_id in flagged

    async def test_one_query_covers_every_device(self, db_session, make_vehicle, seed):
        """Two devices, opposite answers, decided together.

        The settings page asks about the whole fleet at once, so this must not
        become a query per device.
        """
        vin_a, device_a = await make_vehicle("6")
        vin_b, device_b = await make_vehicle("7")
        await seed(vin_a, device_a.device_id, [("0C-ENGINERPM", 1)])
        await seed(vin_b, device_b.device_id, [("BATTERY_VOLTAGE", 1)])

        flagged = await LiveLinkService(db_session).movement_unreadable_device_ids(
            [device_a, device_b]
        )

        assert flagged == {device_a.device_id}

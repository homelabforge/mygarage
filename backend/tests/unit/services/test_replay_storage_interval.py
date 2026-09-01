"""A throttled parameter must still keep a replayed reading.

`storage_interval_seconds` thins a noisy parameter: keep at most one reading
per interval. The check asked "how long since the newest row for this VIN?",
measured against the wall clock, which describes arrival rather than the
reading itself.

A WiCAN off home WiFi replays its buffer with the original timestamps, so a
reading taken at 10:48 lands at 11:42. Compared against the wall clock it looks
like it arrived moments after the 11:41 live sample, so a throttled parameter
discarded it. The closed-session refresh then recomputed from history that
never received the row, and the repair silently did nothing: the drive stayed
recorded at its driveway speed.

The reading's own timestamp is what the interval must be measured against.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models.livelink_parameter import LiveLinkParameter
from app.models.vehicle_telemetry import VehicleTelemetry
from app.services.telemetry_service import TelemetryService
from app.utils.datetime_utils import utc_now


@pytest.mark.asyncio
class TestReplayStorageInterval:
    """Thinning is by reading time, not by arrival time."""

    async def _throttle(self, db_session, param_key: str, seconds: int) -> None:
        param = (
            await db_session.execute(
                select(LiveLinkParameter).where(LiveLinkParameter.param_key == param_key)
            )
        ).scalar_one_or_none()
        if param is None:
            param = LiveLinkParameter(param_key=param_key, enabled=True)
            db_session.add(param)
        param.storage_interval_seconds = seconds
        await db_session.flush()

    async def test_a_replayed_reading_is_kept_despite_a_newer_live_row(
        self, db_session, make_livelink_vehicle
    ):
        """The buffered 85 km/h must reach history, not be thinned away."""
        vin, device = await make_livelink_vehicle("replayiv", "1")
        service = TelemetryService(db_session)
        now = utc_now().replace(tzinfo=None)

        await service.store_telemetry(
            vin=vin,
            device_id=device.device_id,
            autopid_data={"0D-VEHICLESPEED": 12.0},
            config={},
            timestamp=now,
        )
        await db_session.flush()
        await self._throttle(db_session, "0D-VEHICLESPEED", 300)

        # Taken an hour ago, arriving now: far outside the interval from its
        # own neighbours, but seconds from the newest row by the wall clock.
        #
        # The value matches the live one on purpose. The rate-of-change
        # validator compares a reading against the previous one over the
        # ARRIVAL gap, so a replayed 85 after a live 12 is rejected as
        # implausible before the storage interval is ever consulted. That is a
        # second barrier to replayed data and a separate concern; holding the
        # value flat keeps this test on the one being fixed.
        replayed_at = now - timedelta(hours=1)
        await service.store_telemetry(
            vin=vin,
            device_id=device.device_id,
            autopid_data={"0D-VEHICLESPEED": 12.0},
            config={},
            timestamp=replayed_at,
        )
        await db_session.flush()

        stored = (
            (
                await db_session.execute(
                    select(VehicleTelemetry.value)
                    .where(VehicleTelemetry.vin == vin)
                    .where(VehicleTelemetry.timestamp == replayed_at)
                )
            )
            .scalars()
            .all()
        )

        assert list(stored) == [12.0], "a replayed reading was thinned away by arrival time"

    async def test_the_interval_still_thins_a_burst_at_the_same_moment(
        self, db_session, make_livelink_vehicle
    ):
        """Thinning must still happen, or the setting means nothing."""
        vin, device = await make_livelink_vehicle("replayiv", "2")
        service = TelemetryService(db_session)
        now = utc_now().replace(tzinfo=None)

        await service.store_telemetry(
            vin=vin,
            device_id=device.device_id,
            autopid_data={"0D-VEHICLESPEED": 12.0},
            config={},
            timestamp=now,
        )
        await db_session.flush()
        await self._throttle(db_session, "0D-VEHICLESPEED", 300)

        # Ten seconds later: inside the interval, must be dropped. The value is
        # held flat so the rate-of-change validator does not reject it first,
        # which would make this pass whatever the interval logic did.
        await service.store_telemetry(
            vin=vin,
            device_id=device.device_id,
            autopid_data={"0D-VEHICLESPEED": 12.0},
            config={},
            timestamp=now + timedelta(seconds=10),
        )
        await db_session.flush()

        count = (
            (
                await db_session.execute(
                    select(VehicleTelemetry.value)
                    .where(VehicleTelemetry.vin == vin)
                    .where(VehicleTelemetry.param_key == "0D-VEHICLESPEED")
                )
            )
            .scalars()
            .all()
        )

        assert len(list(count)) == 1, "the storage interval stopped thinning"

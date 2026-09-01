"""Changing a device's odometer unit must not silently split its history.

The per-device `odometer_unit` decides how a reading is converted on ingest.
Changing it after readings exist leaves every stored value under the old
interpretation and writes new ones under the new one, so one series holds two
units. That is the state the repair tools now refuse to touch, and it is worse
than it sounds: `odometer_records` keeps the highest reading as a monotonic
floor, so an inflated record is not corrected by later readings, it silences
them.

The selector exists to fix a wrong inference, which realistically happens
before much data exists. Once it does, a setting change is not enough on its
own and the data has to be converted, so the change is refused with the repair
named rather than quietly creating the split.
"""

import pytest

from app.models.vehicle_telemetry import VehicleTelemetry
from app.services.livelink_service import LiveLinkService
from app.utils.datetime_utils import utc_now


@pytest.mark.asyncio
class TestOdometerUnitOverrideGuard:
    """A unit change is allowed until odometer readings depend on it."""

    async def test_changing_the_unit_with_odometer_history_is_refused(
        self, db_session, make_livelink_vehicle
    ):
        vin, device = await make_livelink_vehicle("odoguard", "1")
        device.odometer_unit = "mi"
        db_session.add(
            VehicleTelemetry(
                vin=vin,
                device_id=device.device_id,
                param_key="ODOMETER",
                value=144815.0,
                timestamp=utc_now().replace(tzinfo=None),
                received_at=utc_now().replace(tzinfo=None),
            )
        )
        await db_session.flush()

        with pytest.raises(ValueError, match="already"):
            await LiveLinkService(db_session).update_device(device.device_id, odometer_unit="km")

    async def test_changing_the_unit_before_any_odometer_reading_is_allowed(
        self, db_session, make_livelink_vehicle
    ):
        """The ordinary case: correcting the inference right after setup."""
        vin, device = await make_livelink_vehicle("odoguard", "2")
        device.odometer_unit = "mi"
        await db_session.flush()

        updated = await LiveLinkService(db_session).update_device(
            device.device_id, odometer_unit="km"
        )
        assert updated is not None
        assert updated.odometer_unit == "km"

    async def test_setting_the_same_unit_again_is_not_a_change(
        self, db_session, make_livelink_vehicle
    ):
        """Re-saving the settings panel must not fail on an unchanged value."""
        vin, device = await make_livelink_vehicle("odoguard", "3")
        device.odometer_unit = "mi"
        db_session.add(
            VehicleTelemetry(
                vin=vin,
                device_id=device.device_id,
                param_key="ODOMETER",
                value=144815.0,
                timestamp=utc_now().replace(tzinfo=None),
                received_at=utc_now().replace(tzinfo=None),
            )
        )
        await db_session.flush()

        updated = await LiveLinkService(db_session).update_device(
            device.device_id, odometer_unit="mi"
        )
        assert updated is not None
        assert updated.odometer_unit == "mi"

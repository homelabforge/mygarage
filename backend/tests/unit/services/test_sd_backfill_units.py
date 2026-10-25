"""SD backfill resolves units through the same step as live ingest (R12, R4, T7).

`bulk_backfill` used to convert the odometer from the device's unit and kind
alone, and stored everything else raw, so an R12 mph `SPEED` landed in mph on
the SD path and km/h on the live one, in one column.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device_unit import LiveLinkDeviceUnit
from app.models.vehicle_telemetry import VehicleTelemetry
from app.services.sd_log_parser import SdRow
from app.services.telemetry_service import TelemetryService
from app.utils.datetime_utils import utc_now

pytestmark = pytest.mark.asyncio

P = "t7sdunit"


async def _stored(db: AsyncSession, device_id: str, key: str) -> list[float]:
    rows = await db.execute(
        select(VehicleTelemetry.value)
        .where(VehicleTelemetry.device_id == device_id, VehicleTelemetry.param_key == key)
        .order_by(VehicleTelemetry.timestamp)
    )
    return list(rows.scalars().all())


def _row(key: str, value: float, minutes: int = 0) -> SdRow:
    return SdRow(key, value, utc_now() - timedelta(days=2, minutes=-minutes))


def _unit(device_id: str, key: str, unit: str, cls: str, source: str) -> LiveLinkDeviceUnit:
    return LiveLinkDeviceUnit(
        device_id=device_id, param_key=key, unit=unit, param_class=cls, source=source
    )


async def test_an_r12_mph_speed_is_stored_as_kmh(db_session: AsyncSession, make_livelink_vehicle):
    """The SD path stores the same km/h the live path does for a declared mph key."""
    vin, device = await make_livelink_vehicle(P, "1")
    db_session.add(_unit(device.device_id, "SPEED", "mph", "speed", "wire"))
    await db_session.commit()

    await TelemetryService(db_session).bulk_backfill(vin, device.device_id, [_row("SPEED", 50.0)])

    assert await _stored(db_session, device.device_id, "SPEED") == [pytest.approx(50 * 1.609344)]


async def test_a_legacy_odometer_row_reads_miles(db_session: AsyncSession, make_livelink_vehicle):
    """Migration 133's legacy row decides the SD odometer like the live one."""
    vin, device = await make_livelink_vehicle(P, "2")
    db_session.add(_unit(device.device_id, "ODOMETER", "mi", "distance", "legacy"))
    await db_session.commit()

    await TelemetryService(db_session).bulk_backfill(
        vin, device.device_id, [_row("ODOMETER", 1000.0)]
    )

    # `UnitConverter.miles_to_km` rounds to the hundredth, as live ingest does.
    assert await _stored(db_session, device.device_id, "ODOMETER") == [1609.34]


async def test_a_bare_odometer_with_no_unit_is_km(db_session: AsyncSession, make_livelink_vehicle):
    """Upstream's `ODOMETER` is km on the SD path too."""
    vin, device = await make_livelink_vehicle(P, "3")
    await db_session.commit()

    await TelemetryService(db_session).bulk_backfill(
        vin, device.device_id, [_row("ODOMETER", 1000.0)]
    )

    assert await _stored(db_session, device.device_id, "ODOMETER") == [1000.0]


async def test_only_the_declared_odometer_key_is_converted(
    db_session: AsyncSession, make_livelink_vehicle
):
    """A declared `odometer_param_key` replaces name matching on the live path,
    so a second odometer-looking key isn't converted there. The SD path used to
    convert every name match, so one key held two scales."""
    vin, device = await make_livelink_vehicle(P, "4", odometer_param_key="A6-ODOMETER")
    await db_session.commit()

    await TelemetryService(db_session).bulk_backfill(
        vin, device.device_id, [_row("MILEAGE", 1000.0), _row("A6-ODOMETER", 2000.0, 1)]
    )

    assert await _stored(db_session, device.device_id, "MILEAGE") == [1000.0]
    assert await _stored(db_session, device.device_id, "A6-ODOMETER") == [2000.0]


async def test_a_non_finite_row_is_dropped(db_session: AsyncSession, make_livelink_vehicle):
    """NaN binds as NULL into a NOT NULL column; the rest of the file still lands."""
    vin, device = await make_livelink_vehicle(P, "5")
    await db_session.commit()

    inserted = await TelemetryService(db_session).bulk_backfill(
        vin,
        device.device_id,
        [_row("COOLANT", float("nan")), _row("COOLANT", float("inf"), 1), _row("COOLANT", 90.0, 2)],
    )

    assert inserted == 1
    assert await _stored(db_session, device.device_id, "COOLANT") == [90.0]

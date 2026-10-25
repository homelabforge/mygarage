"""An SD-card odometer goes through live ingest's rounding and sanity checks (B6-11).

`store_telemetry` rounds an odometer to whole km and drops one past the 1.6M km
cap or more than 16,000 km above the vehicle's highest record
(`_sanitize_odometer_value`). `bulk_backfill` wrote straight to the columns, so
an SD pull stored 80100.6 where live ingest stores 80101, and a garbage
0xFFFFFF reading landed in the latest table as the vehicle's odometer.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.odometer import OdometerRecord
from app.models.vehicle_telemetry import VehicleTelemetry, VehicleTelemetryLatest
from app.services.sd_log_parser import SdRow
from app.services.telemetry_service import TelemetryService

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 9, 10, 8, 0, 0)


async def _seed(db: AsyncSession, make_livelink_vehicle, suffix: str) -> tuple[str, str]:
    # A unit on the device, so the values below aren't converted on the way in.
    vin, device = await make_livelink_vehicle("b611sd", suffix, odometer_unit="km")
    db.add(OdometerRecord(vin=vin, date=date(2026, 9, 1), odometer_km=80000, source="manual"))
    await db.commit()
    return vin, device.device_id


async def _stored(db: AsyncSession, device_id: str) -> dict[datetime, float]:
    rows = await db.execute(
        select(VehicleTelemetry.timestamp, VehicleTelemetry.value).where(
            VehicleTelemetry.device_id == device_id, VehicleTelemetry.param_key == "ODOMETER"
        )
    )
    return {ts: value for ts, value in rows.all()}


async def test_an_sd_odometer_is_rounded_like_a_live_one(
    db_session: AsyncSession, make_livelink_vehicle
):
    """Red on ed8fbef9: stored 80100.6."""
    vin, device_id = await _seed(db_session, make_livelink_vehicle, "1")

    await TelemetryService(db_session).bulk_backfill(
        vin, device_id, [SdRow("ODOMETER", 80100.6, T0)]
    )

    assert await _stored(db_session, device_id) == {T0: 80101.0}
    latest = await db_session.scalar(
        select(VehicleTelemetryLatest.value).where(
            VehicleTelemetryLatest.vin == vin, VehicleTelemetryLatest.param_key == "ODOMETER"
        )
    )
    assert latest == 80101.0


async def test_an_sd_odometer_past_the_cap_or_the_jump_is_dropped(
    db_session: AsyncSession, make_livelink_vehicle
):
    """Live ingest drops both, so the SD path does too. Red on ed8fbef9, which
    stored all three and made the 16,777,215 km reading the latest."""
    vin, device_id = await _seed(db_session, make_livelink_vehicle, "2")
    later = [T0 + timedelta(minutes=i) for i in range(3)]

    await TelemetryService(db_session).bulk_backfill(
        vin,
        device_id,
        [
            SdRow("ODOMETER", 80200.0, later[0]),
            # 0xFFFFFF: past the 1.6M km cap.
            SdRow("ODOMETER", 16777215.0, later[1]),
            # More than 16,000 km above the 80,000 km record.
            SdRow("ODOMETER", 96500.0, later[2]),
        ],
    )

    assert await _stored(db_session, device_id) == {later[0]: 80200.0}
    latest = await db_session.scalar(
        select(VehicleTelemetryLatest.value).where(
            VehicleTelemetryLatest.vin == vin, VehicleTelemetryLatest.param_key == "ODOMETER"
        )
    )
    assert latest == 80200.0

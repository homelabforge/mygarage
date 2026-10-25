"""WiCAN odometer units through the real ingest pipeline (D6a, N-1).

Main read every bare WiCAN key as miles and ignored the HTTPS `config` unit,
so a profile-based WiCAN with no unit set stored its odometer 1.609x high.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle_telemetry import VehicleTelemetry, VehicleTelemetryLatest
from app.schemas.livelink_ingest import WiCANPayload
from app.services.livelink_ingest import ingest
from app.services.livelink_sources.base import MqttEnvelope, WicanHttpsEnvelope
from app.services.livelink_sources.wican import WicanModule

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("livelink_enabled")]

P = "t7wican"


async def _stored(db: AsyncSession, device_id: str, key: str) -> list[float]:
    rows = await db.execute(
        select(VehicleTelemetry.value).where(
            VehicleTelemetry.device_id == device_id, VehicleTelemetry.param_key == key
        )
    )
    return list(rows.scalars().all())


async def _rx(db: AsyncSession, device_id: str, **values: float) -> None:
    await ingest(
        WicanModule(), MqttEnvelope(f"wican/{device_id}/can/rx", json.dumps(values).encode()), db
    )
    await db.commit()


async def test_a_bare_odometer_on_a_wican_with_no_unit_is_stored_as_km(
    db_session: AsyncSession, make_livelink_vehicle
):
    """Upstream's `ODOMETER` is kilometres."""
    _vin, device = await make_livelink_vehicle(P, "1")
    await db_session.commit()

    await _rx(db_session, device.device_id, ODOMETER=80000)

    assert await _stored(db_session, device.device_id, "ODOMETER") == [80000.0]


async def test_odometer_mi_is_stored_as_km(db_session: AsyncSession, make_livelink_vehicle):
    """Regression guard: main's substring scan already read `ODOMETER_MI` as a
    miles odometer; the exact-set predicate now agrees."""
    _vin, device = await make_livelink_vehicle(P, "2")
    await db_session.commit()

    await _rx(db_session, device.device_id, ODOMETER_MI=50000)

    assert await _stored(db_session, device.device_id, "ODOMETER_MI") == [80467.0]


async def test_a_declared_config_unit_beats_the_key_rule(
    db_session: AsyncSession, make_livelink_vehicle
):
    """`MILEAGE` would be guessed as miles; the boot config says km."""
    vin, device = await make_livelink_vehicle(P, "3")
    await db_session.commit()

    payload = WiCANPayload.model_validate(
        {
            "autopid_data": {"MILEAGE": 80000},
            "config": {"MILEAGE": {"class": "distance", "unit": "km"}},
            "status": {"device_id": device.device_id, "ecu_status": "online"},
        }
    )
    await ingest(WicanModule(), WicanHttpsEnvelope(device.device_id, payload), db_session)
    await db_session.commit()

    assert await _stored(db_session, device.device_id, "MILEAGE") == [80000.0]

    # The next frame carries no config; the R12 row keeps it km.
    await _rx(db_session, device.device_id, MILEAGE=80010)
    latest = await db_session.execute(
        select(VehicleTelemetryLatest.value).where(
            VehicleTelemetryLatest.vin == vin, VehicleTelemetryLatest.param_key == "MILEAGE"
        )
    )
    assert latest.scalar_one() == 80010.0


async def test_a_device_unit_still_wins_over_a_declared_one(
    db_session: AsyncSession, make_livelink_vehicle
):
    """Regression guard on the order: the device's `odometer_unit` first."""
    _vin, device = await make_livelink_vehicle(P, "4", odometer_unit="mi")
    await db_session.commit()

    payload = WiCANPayload.model_validate(
        {
            "autopid_data": {"ODOMETER": 50000},
            "config": {"ODOMETER": {"class": "distance", "unit": "km"}},
            "status": {"device_id": device.device_id, "ecu_status": "online"},
        }
    )
    await ingest(WicanModule(), WicanHttpsEnvelope(device.device_id, payload), db_session)
    await db_session.commit()

    assert await _stored(db_session, device.device_id, "ODOMETER") == [80467.0]


async def test_store_telemetry_reads_a_stored_row_without_a_config(
    db_session: AsyncSession, make_livelink_vehicle
):
    """`store_telemetry` called on its own, with no `config`, still resolves
    the odometer through the device's R12 row (here migration 133's legacy
    one), so it can't disagree with the pipeline."""
    from app.models.livelink_device_unit import LiveLinkDeviceUnit
    from app.services.telemetry_service import TelemetryService

    vin, device = await make_livelink_vehicle(P, "5")
    db_session.add(
        LiveLinkDeviceUnit(
            device_id=device.device_id,
            param_key="ODOMETER",
            unit="mi",
            param_class="distance",
            source="legacy",
        )
    )
    await db_session.commit()

    await TelemetryService(db_session).store_telemetry(
        vin=vin, device_id=device.device_id, autopid_data={"ODOMETER": 50000.0}, config={}
    )
    await db_session.commit()

    assert await _stored(db_session, device.device_id, "ODOMETER") == [80467.0]

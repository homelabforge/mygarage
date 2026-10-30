"""A Torque phone that has sent its odometer can still be told which key it is (FW-A-r3, N1).

Torque records an odometer only from a key the device declares. Its raw rows
carry `TORQUE_ODOMETER` long before that, which is what the parameter picker
offers. Counting those rows as odometer history 409'd the very PUT that
declares it, with no way out: the latest row never prunes.

It declares with `km`: `mi` with this key is refused on its own grounds
(test_torque_odometer_unit.py).
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.models.vehicle_telemetry import VehicleTelemetry
from app.utils.datetime_utils import utc_now

pytestmark = pytest.mark.usefixtures("test_vehicle")

VIN = "1HGBH41JXMN109186"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_torque_device_declares_its_odometer_after_sending_it(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    """Red on 4e32c6eb: 409."""
    now = utc_now()
    db_session.add(LiveLinkDevice(device_id="torqdecl0001", vin=VIN, kind="torque", enabled=True))
    db_session.add(
        VehicleTelemetry(
            vin=VIN,
            device_id="torqdecl0001",
            param_key="TORQUE_ODOMETER",
            value=80000.0,
            timestamp=now,
            received_at=now,
        )
    )
    await db_session.commit()
    try:
        response = await client.put(
            "/api/livelink/devices/torqdecl0001",
            headers=auth_headers,
            json={"odometer_param_key": "TORQUE_ODOMETER", "odometer_unit": "km"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["odometer_param_key"], body["odometer_unit"]) == ("TORQUE_ODOMETER", "km")
    finally:
        await db_session.rollback()
        await db_session.execute(
            delete(VehicleTelemetry).where(VehicleTelemetry.device_id == "torqdecl0001")
        )
        await db_session.execute(
            delete(LiveLinkDevice).where(LiveLinkDevice.device_id == "torqdecl0001")
        )
        await db_session.commit()

"""The odometer selection must survive the real API, not just an ORM assignment.

A unit test that assigns `device.odometer_param_key` directly passes even when
the schema, route and service never learned the field exists: the response model
is built with model_validate, which drops any attribute it does not declare.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.models.livelink_device import LiveLinkDevice
from app.models.vehicle import Vehicle

URL = "/api/livelink/devices"


@pytest_asyncio.fixture
async def device(db_session, test_user):
    """An isolated vehicle plus Torque device, cleaned up after."""
    suffix = uuid.uuid4().hex[:10]
    vin = f"ODOAPI{suffix.upper()}X"[:17]
    device_id = f"odoapi{suffix}"
    db_session.add(
        Vehicle(vin=vin, user_id=test_user["id"], nickname="Odo API", vehicle_type="Car")
    )
    await db_session.flush()
    db_session.add(LiveLinkDevice(device_id=device_id, kind="torque", vin=vin, enabled=True))
    await db_session.commit()
    yield device_id
    await db_session.execute(delete(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id))
    await db_session.execute(delete(Vehicle).where(Vehicle.vin == vin))
    await db_session.commit()


@pytest.mark.asyncio
async def test_the_selection_round_trips(client, auth_headers, db_session, device):
    # km, not mi: a Torque device can't read TORQUE_ODOMETER as miles (O-T6).
    resp = await client.put(
        f"{URL}/{device}",
        json={"odometer_param_key": "TORQUE_ODOMETER", "odometer_unit": "km"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["odometer_param_key"] == "TORQUE_ODOMETER", (
        "the response schema must DECLARE the field or model_validate drops it"
    )

    db_session.expire_all()
    row = (
        await db_session.execute(select(LiveLinkDevice).where(LiveLinkDevice.device_id == device))
    ).scalar_one()
    assert row.odometer_param_key == "TORQUE_ODOMETER", "the column must actually persist"


@pytest.mark.asyncio
async def test_the_value_is_uppercased(client, auth_headers, device):
    """Compared case-sensitively against stored keys, so lowercase never matches."""
    resp = await client.put(
        f"{URL}/{device}", json={"odometer_param_key": "torque_odometer"}, headers=auth_headers
    )
    assert resp.json()["odometer_param_key"] == "TORQUE_ODOMETER"


@pytest.mark.asyncio
async def test_an_empty_string_clears_it(client, auth_headers, device):
    await client.put(
        f"{URL}/{device}", json={"odometer_param_key": "TORQUE_ODOMETER"}, headers=auth_headers
    )
    resp = await client.put(
        f"{URL}/{device}", json={"odometer_param_key": ""}, headers=auth_headers
    )
    assert resp.json()["odometer_param_key"] is None


@pytest.mark.asyncio
async def test_omitting_it_leaves_it_untouched(client, auth_headers, device):
    await client.put(
        f"{URL}/{device}", json={"odometer_param_key": "TORQUE_ODOMETER"}, headers=auth_headers
    )
    resp = await client.put(f"{URL}/{device}", json={"label": "renamed"}, headers=auth_headers)
    assert resp.json()["odometer_param_key"] == "TORQUE_ODOMETER"


@pytest.mark.asyncio
async def test_param_keys_endpoint_is_per_device(client, auth_headers, db_session, device):
    """Per-device, because vehicle_telemetry_latest has no device_id column."""
    from app.models.vehicle_telemetry import VehicleTelemetry
    from app.utils.datetime_utils import utc_now

    row = (
        await db_session.execute(select(LiveLinkDevice).where(LiveLinkDevice.device_id == device))
    ).scalar_one()
    db_session.add(
        VehicleTelemetry(
            vin=row.vin,
            device_id=device,
            param_key="TORQUE_ODOMETER",
            value=90170.0,
            timestamp=utc_now(),
        )
    )
    await db_session.commit()

    resp = await client.get(f"{URL}/{device}/param-keys", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == ["TORQUE_ODOMETER"]


@pytest.mark.asyncio
async def test_non_admins_are_refused(client, non_admin_headers, device):
    resp = await client.put(
        f"{URL}/{device}", json={"odometer_param_key": "TORQUE_ODOMETER"}, headers=non_admin_headers
    )
    assert resp.status_code in (401, 403)

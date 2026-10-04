"""What `/livelink/status` reports a vehicle's sources can do.

The frontend gates the LiveLink sub-tabs on this list. Before it existed, any
vehicle with any linked device got the full OBD2 tab set, so a propane tank
sensor on a fifth wheel was offered DTCs, drive sessions and trips, and its
live dashboard read "Vehicle Parked". The capability declarations had been on
the source modules the whole time with no reader on the presentation side.
"""

import itertools

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.models.user import User
from app.models.vehicle import Vehicle
from app.routes.livelink_vehicle import _union_capabilities
from app.services.livelink_service import LiveLinkService
from app.utils.datetime_utils import utc_now

_SEQ = itertools.count()


async def _make_vehicle(db_session: AsyncSession) -> str:
    """Create a minimal user + vehicle, return the (unique) vin."""
    n = next(_SEQ)
    user = User(
        username=f"caps_user_{n}",
        email=f"caps_{n}@example.com",
        hashed_password="x",
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.flush()

    vin = f"CAPSTEST{n:09d}"  # 17 chars
    vehicle = Vehicle(
        vin=vin,
        user_id=user.id,
        nickname=f"Caps Car {n}",
        vehicle_type="Car",
    )
    db_session.add(vehicle)
    await db_session.flush()
    return vin


def _device(vin: str, kind: str) -> LiveLinkDevice:
    return LiveLinkDevice(
        device_id=f"{kind[:2]}{next(_SEQ):010d}",
        vin=vin,
        kind=kind,
        enabled=True,
        last_seen=utc_now(),
    )


@pytest.mark.asyncio
async def test_generic_mqtt_declares_telemetry_and_nothing_else(db_session: AsyncSession):
    """The gate that keeps an OBD2 dashboard off a propane trailer.

    Every capability named here is one whose sub-tab the frontend hides. If
    `generic_mqtt` ever acquires one of them, the tab returns.
    """
    vin = await _make_vehicle(db_session)
    db_session.add(_device(vin, "generic_mqtt"))
    await db_session.commit()

    devices = await LiveLinkService(db_session).list_devices_by_vin(vin)

    assert _union_capabilities(devices) == ["telemetry"]


@pytest.mark.asyncio
async def test_wican_declares_the_capabilities_its_tabs_need(db_session: AsyncSession):
    """The positive control: gating must not hide tabs that do have a source."""
    vin = await _make_vehicle(db_session)
    db_session.add(_device(vin, "wican"))
    await db_session.commit()

    devices = await LiveLinkService(db_session).list_devices_by_vin(vin)
    caps = _union_capabilities(devices)

    assert {"telemetry", "drive_session", "dtc"} <= set(caps)


@pytest.mark.asyncio
async def test_capabilities_are_a_union_across_every_linked_device(db_session: AsyncSession):
    """A trailer carrying both sources gets both sets.

    `get_device_by_vin` returns only the most-recently-active device, so
    answering from it would drop whichever source reported second — and which
    one that is changes every time a message arrives.
    """
    vin = await _make_vehicle(db_session)
    db_session.add_all([_device(vin, "wican"), _device(vin, "generic_mqtt")])
    await db_session.commit()

    service = LiveLinkService(db_session)
    devices = await service.list_devices_by_vin(vin)
    assert len(devices) == 2

    wican_only = _union_capabilities([d for d in devices if d.kind == "wican"])
    assert set(_union_capabilities(devices)) == set(wican_only) | {"telemetry"}
    assert "dtc" in _union_capabilities(devices)


@pytest.mark.asyncio
async def test_unregistered_kind_contributes_nothing(db_session: AsyncSession):
    """Fail closed: an unknown source hides gated tabs rather than showing all."""
    vin = await _make_vehicle(db_session)
    device = _device(vin, "generic_mqtt")
    device.kind = "unregistered_kind"
    db_session.add(device)
    await db_session.commit()

    devices = await LiveLinkService(db_session).list_devices_by_vin(vin)

    assert _union_capabilities(devices) == []


@pytest.mark.asyncio
async def test_no_devices_means_no_capabilities(db_session: AsyncSession):
    vin = await _make_vehicle(db_session)
    await db_session.commit()

    devices = await LiveLinkService(db_session).list_devices_by_vin(vin)

    assert devices == []
    assert _union_capabilities(devices) == []

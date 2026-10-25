"""Unlinking or relinking a device mid-drive ends that drive (R8, B-8).

The UI unlinks through `PUT /devices/{id}` with `vin=""`, which used to leave
`current_session_id` pointing at an open session on the old vehicle: the drive
never closed, and the device's next movement on the new vehicle extended it.
"""

import uuid
from datetime import timedelta

import pytest

from app.models.drive_session import DriveSession
from app.models.livelink_device import LiveLinkDevice
from app.models.vehicle import Vehicle
from app.utils.datetime_utils import utc_now

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _vehicle(db_session, test_user) -> str:
    vin = f"UL{uuid.uuid4().hex[:15].upper()}"
    db_session.add(Vehicle(vin=vin, user_id=test_user["id"], nickname="Car", vehicle_type="Car"))
    await db_session.commit()
    return vin


async def _driving(db_session, vin: str, **session_fields) -> tuple[LiveLinkDevice, DriveSession]:
    """A WiCAN on `vin` whose pointer names `session`."""
    now = utc_now()
    device = LiveLinkDevice(
        device_id=f"ul{uuid.uuid4().hex[:10]}",
        vin=vin,
        enabled=True,
        kind="wican",
        device_status="online",
        last_seen=now - timedelta(seconds=20),
    )
    session = DriveSession(
        vin=vin,
        device_id=device.device_id,
        started_at=now - timedelta(minutes=30),
        **session_fields,
    )
    db_session.add_all([device, session])
    await db_session.flush()
    device.current_session_id = session.id
    await db_session.commit()
    return device, session


async def _reload(db_session, device: LiveLinkDevice, session: DriveSession):
    # Ids first: after expire_all a plain attribute read would lazy-load.
    device_pk, session_pk = device.id, session.id
    db_session.expire_all()
    return (
        await db_session.get(LiveLinkDevice, device_pk),
        await db_session.get(DriveSession, session_pk),
    )


def _naive(value):
    return value.replace(tzinfo=None) if value is not None and value.tzinfo else value


async def test_unlinking_mid_drive_ends_the_drive_at_its_last_movement(
    client, auth_headers, db_session, test_user
):
    vin = await _vehicle(db_session, test_user)
    moved = utc_now() - timedelta(minutes=4)
    device, session = await _driving(
        db_session,
        vin,
        movement_started_at=utc_now() - timedelta(minutes=29),
        movement_ended_at=moved,
    )

    resp = await client.put(
        f"/api/livelink/devices/{device.device_id}", json={"vin": ""}, headers=auth_headers
    )

    assert resp.status_code == 200, resp.text
    device, session = await _reload(db_session, device, session)
    assert _naive(session.ended_at) == _naive(moved)
    assert device.vin is None
    assert device.current_session_id is None
    assert session.duration_seconds == pytest.approx(26 * 60, abs=2)


async def test_relinking_mid_drive_ends_the_drive_on_the_old_vehicle(
    client, auth_headers, db_session, test_user
):
    """A drive with no movement record (Torque-style) ends at the last contact."""
    old_vin = await _vehicle(db_session, test_user)
    new_vin = await _vehicle(db_session, test_user)
    device, session = await _driving(db_session, old_vin)
    last_seen = device.last_seen

    resp = await client.put(
        f"/api/livelink/devices/{device.device_id}", json={"vin": new_vin}, headers=auth_headers
    )

    assert resp.status_code == 200, resp.text
    device, session = await _reload(db_session, device, session)
    assert device.vin == new_vin
    assert device.current_session_id is None
    assert session.vin == old_vin
    assert _naive(session.ended_at) == _naive(last_seen)


async def test_unlinking_with_a_closed_pointer_just_clears_it(
    client, auth_headers, db_session, test_user
):
    """A pointer held on a CLOSED session (awaiting a reopen) is let go; the
    session itself isn't restamped."""
    vin = await _vehicle(db_session, test_user)
    ended = utc_now() - timedelta(minutes=10)
    device, session = await _driving(db_session, vin, ended_at=ended, duration_seconds=1200)

    resp = await client.put(
        f"/api/livelink/devices/{device.device_id}", json={"vin": ""}, headers=auth_headers
    )

    assert resp.status_code == 200, resp.text
    device, session = await _reload(db_session, device, session)
    assert device.current_session_id is None
    assert _naive(session.ended_at) == _naive(ended)
    assert session.duration_seconds == 1200


async def test_an_update_that_keeps_the_vehicle_leaves_the_drive_alone(
    client, auth_headers, db_session, test_user
):
    """Regression guard: a rename, or resending the same VIN, isn't a relink."""
    vin = await _vehicle(db_session, test_user)
    device, session = await _driving(db_session, vin, movement_ended_at=utc_now())

    resp = await client.put(
        f"/api/livelink/devices/{device.device_id}",
        json={"label": "Dongle", "vin": vin.lower()},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    device, session = await _reload(db_session, device, session)
    assert device.current_session_id == session.id
    assert session.ended_at is None

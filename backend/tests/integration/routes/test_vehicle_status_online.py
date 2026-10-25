"""The vehicle page's online flag uses the integrations card's rule.

A Mopeka sensor has no status topic, so its `device_status` stays 'unknown'
for ever. The vehicle page read that field raw and showed the RV offline while
the settings card, which asks "has it reported recently", said receiving.
"""

import uuid
from datetime import timedelta

import pytest

from app.models.livelink_device import LiveLinkDevice
from app.models.vehicle import Vehicle
from app.utils.datetime_utils import utc_now


async def _vehicle(db_session, test_user) -> str:
    """A vehicle of its own: `test_vehicle` carries other tests' devices, and
    the status reports whichever device reported last."""
    vin = f"OL{uuid.uuid4().hex[:15].upper()}"
    db_session.add(Vehicle(vin=vin, user_id=test_user["id"], nickname="RV", vehicle_type="RV"))
    await db_session.commit()
    return vin


async def _device(db_session, vin: str, **fields) -> None:
    db_session.add(
        LiveLinkDevice(
            device_id=f"ol{uuid.uuid4().hex[:10]}", vin=vin, **{"enabled": True, **fields}
        )
    )
    await db_session.commit()


async def _status(client, auth_headers, vin: str) -> dict:
    response = await client.get(f"/api/vehicles/{vin}/livelink/status", headers=auth_headers)
    assert response.status_code == 200
    return response.json()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_sensor_with_no_status_topic_is_online_while_it_reports(
    client, auth_headers, db_session, test_user
):
    vin = await _vehicle(db_session, test_user)
    await _device(
        db_session,
        vin,
        kind="generic_mqtt",
        device_status="unknown",
        last_seen=utc_now() - timedelta(minutes=1),
    )

    body = await _status(client, auth_headers, vin)

    assert body["device_status"] == "unknown"
    assert body["online"] is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_sensor_that_has_gone_quiet_is_offline(client, auth_headers, db_session, test_user):
    vin = await _vehicle(db_session, test_user)
    await _device(
        db_session,
        vin,
        kind="generic_mqtt",
        device_status="unknown",
        last_seen=utc_now() - timedelta(hours=10),
    )

    assert (await _status(client, auth_headers, vin))["online"] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_wican_that_says_online_is_online(client, auth_headers, db_session, test_user):
    """Unchanged for a source that does report its status."""
    vin = await _vehicle(db_session, test_user)
    await _device(db_session, vin, kind="wican", device_status="online", last_seen=utc_now())

    assert (await _status(client, auth_headers, vin))["online"] is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_switched_off_device_is_offline_whatever_it_last_said(
    client, auth_headers, db_session, test_user
):
    """A disabled device freezes at its last status: ingest returns before the
    status update and the offline sweep skips it."""
    vin = await _vehicle(db_session, test_user)
    await _device(
        db_session, vin, kind="wican", device_status="online", last_seen=utc_now(), enabled=False
    )

    assert (await _status(client, auth_headers, vin))["online"] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_device_is_offline(client, auth_headers, db_session, test_user):
    vin = await _vehicle(db_session, test_user)

    assert (await _status(client, auth_headers, vin))["online"] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_held_closed_session_is_not_reported_as_current(
    client, auth_headers, db_session, test_user
):
    """T4-b: the pointer can hold a CLOSED session (awaiting, or a held replay).

    The status used to call it current and count its duration up from hours ago.
    """
    from app.models.drive_session import DriveSession

    vin = await _vehicle(db_session, test_user)
    device_id = f"ol{uuid.uuid4().hex[:10]}"
    started = utc_now() - timedelta(hours=3)
    held = DriveSession(
        vin=vin,
        device_id=device_id,
        started_at=started,
        ended_at=started + timedelta(minutes=20),
        duration_seconds=1200,
    )
    device = LiveLinkDevice(
        device_id=device_id,
        vin=vin,
        enabled=True,
        kind="wican",
        device_status="online",
        last_seen=utc_now() - timedelta(minutes=1),
    )
    db_session.add_all([device, held])
    await db_session.flush()
    device.current_session_id = held.id
    await db_session.commit()

    body = await _status(client, auth_headers, vin)

    assert body["current_session_id"] is None
    assert body["session_started_at"] is None
    assert body["session_duration_seconds"] is None

"""The session-detail route reads the session's own window (carry 14, T5-a).

It used to ask for the VIN's telemetry between `started_at` and `ended_at`,
inclusive at both ends, with `limit=1` for the parameter list. So it counted
another device's rows on the same car, the sample a touching earlier drive
already owns, and listed one parameter whatever the drive recorded. It now
reads through SessionService's window, the one the drive's figures come from.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.models.drive_session import DriveSession
from app.models.livelink_device import LiveLinkDevice
from app.models.vehicle import Vehicle
from app.models.vehicle_telemetry import VehicleTelemetry
from app.services.session_boundaries import BOUNDARY_ALGORITHM_MOVEMENT

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

START = datetime(2026, 9, 10, 8, 0, 0)
END = START + timedelta(minutes=20)


async def _vehicle_with_device(db_session, test_user) -> tuple[str, str]:
    vin = f"SD{uuid.uuid4().hex[:15].upper()}"
    device_id = f"sd{uuid.uuid4().hex[:10]}"
    db_session.add(Vehicle(vin=vin, user_id=test_user["id"], nickname="Car", vehicle_type="Car"))
    await db_session.flush()
    db_session.add(LiveLinkDevice(device_id=device_id, vin=vin, enabled=True, kind="wican"))
    await db_session.flush()
    return vin, device_id


def _session(vin: str, device_id: str, start: datetime, end: datetime) -> DriveSession:
    return DriveSession(
        vin=vin,
        device_id=device_id,
        started_at=start,
        ended_at=end,
        duration_seconds=int((end - start).total_seconds()),
        boundary_algorithm_version=BOUNDARY_ALGORITHM_MOVEMENT,
    )


def _row(vin: str, device_id: str, key: str, at: datetime) -> VehicleTelemetry:
    return VehicleTelemetry(
        vin=vin, device_id=device_id, param_key=key, value=1.0, timestamp=at, received_at=at
    )


async def _detail(client, auth_headers, vin: str, session_id: int) -> dict:
    response = await client.get(
        f"/api/vehicles/{vin}/livelink/sessions/{session_id}", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_another_devices_rows_on_the_car_are_not_the_sessions(
    client, auth_headers, db_session, test_user
):
    """A propane sensor on the trailer reports all through the drive."""
    vin, device_id = await _vehicle_with_device(db_session, test_user)
    sensor = f"sd{uuid.uuid4().hex[:10]}"
    db_session.add(LiveLinkDevice(device_id=sensor, vin=vin, enabled=True, kind="generic_mqtt"))
    drive = _session(vin, device_id, START, END)
    db_session.add(drive)
    db_session.add(_row(vin, device_id, "SPEED", START + timedelta(minutes=5)))
    for minute in (2, 7, 12):
        db_session.add(_row(vin, sensor, "PROPANE_T1_LEVEL_PCT", START + timedelta(minutes=minute)))
    await db_session.commit()

    body = await _detail(client, auth_headers, vin, drive.id)

    assert body["parameters_recorded"] == ["SPEED"]
    assert body["data_points_count"] == 1


async def test_the_sample_a_touching_earlier_drive_owns_is_not_counted(
    client, auth_headers, db_session, test_user
):
    """The previous drive ended exactly where this one starts, so the reading
    at that instant is the previous one's (R11)."""
    vin, device_id = await _vehicle_with_device(db_session, test_user)
    db_session.add(_session(vin, device_id, START - timedelta(minutes=30), START))
    drive = _session(vin, device_id, START, END)
    db_session.add(drive)
    db_session.add(_row(vin, device_id, "SHARED_EDGE", START))
    db_session.add(_row(vin, device_id, "SPEED", START + timedelta(minutes=1)))
    await db_session.commit()

    body = await _detail(client, auth_headers, vin, drive.id)

    assert body["parameters_recorded"] == ["SPEED"]
    assert body["data_points_count"] == 1


async def test_every_parameter_the_drive_recorded_is_listed(
    client, auth_headers, db_session, test_user
):
    """`limit=1` listed whichever single row came first."""
    vin, device_id = await _vehicle_with_device(db_session, test_user)
    drive = _session(vin, device_id, START, END)
    db_session.add(drive)
    for minute, key in ((1, "SPEED"), (2, "ENGINE_RPM"), (3, "COOLANT_TMP"), (4, "SPEED")):
        db_session.add(_row(vin, device_id, key, START + timedelta(minutes=minute)))
    await db_session.commit()

    body = await _detail(client, auth_headers, vin, drive.id)

    assert sorted(body["parameters_recorded"]) == ["COOLANT_TMP", "ENGINE_RPM", "SPEED"]
    assert body["data_points_count"] == 4


async def test_an_open_session_lists_nothing(client, auth_headers, db_session, test_user):
    """Regression guard: no end, no window, as before."""
    vin, device_id = await _vehicle_with_device(db_session, test_user)
    drive = DriveSession(vin=vin, device_id=device_id, started_at=START)
    db_session.add(drive)
    db_session.add(_row(vin, device_id, "SPEED", START + timedelta(minutes=1)))
    await db_session.commit()

    body = await _detail(client, auth_headers, vin, drive.id)

    assert (body["parameters_recorded"], body["data_points_count"]) == ([], 0)

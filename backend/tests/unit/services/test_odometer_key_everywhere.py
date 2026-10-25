"""One answer to "is this key an odometer", everywhere it's asked (ruling FW-A-r2).

Live ingest has always converted and recorded odometers by a substring scan
(`is_converted_odometer_key`), so an autopid named `ODOMETER_KM` writes
odometer records. The 409 unit guard and the session odometers asked the
exact six-name set instead, and didn't see it. Now they ask the same thing.

The exact set was there to keep trip counters out (`21-DISTANCEMILON`,
`31-DISTANCESINCECODECLEAR`), and the scan doesn't take them either, which the
guard at the bottom pins.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.models.vehicle_telemetry import VehicleTelemetry, VehicleTelemetryLatest
from app.services.livelink_service import LiveLinkService
from app.services.session_service import SessionService
from app.utils.datetime_utils import utc_now
from app.utils.odometer_units import is_recorded_odometer_key

pytestmark = pytest.mark.asyncio

P = "fwar2"
TRIP_COUNTERS = ("21-DISTANCEMILON", "31-DISTANCESINCECODECLEAR")


def _raw(vin: str, device_id: str, key: str, value: float, at) -> VehicleTelemetry:
    return VehicleTelemetry(
        vin=vin, device_id=device_id, param_key=key, value=value, timestamp=at, received_at=at
    )


async def test_the_unit_guard_sees_an_odometer_km_history(
    db_session: AsyncSession, make_livelink_vehicle
):
    """Its records were written from `ODOMETER_KM`, so changing the unit now
    would split them. Red on 7210744c: no 409."""
    vin, device = await make_livelink_vehicle(P, "1")
    db_session.add(_raw(vin, device.device_id, "ODOMETER_KM", 80000.0, utc_now()))
    await db_session.flush()

    assert await LiveLinkService(db_session).device_has_odometer_history(device) is True
    with pytest.raises(ValueError, match="already been recorded"):
        await LiveLinkService(db_session).update_device(device.device_id, {"odometer_unit": "mi"})


async def test_a_session_starts_on_an_odometer_km_reading(
    db_session: AsyncSession, make_livelink_vehicle
):
    """Red on 7210744c: no start odometer."""
    vin, device = await make_livelink_vehicle(P, "2")
    now = utc_now()
    db_session.add(
        VehicleTelemetryLatest(
            vin=vin, param_key="ODOMETER_KM", value=80123.0, timestamp=now, received_at=now
        )
    )
    await db_session.flush()

    session = await SessionService(db_session).start_session(device, now)

    assert session.start_odometer == 80123.0


async def test_a_session_takes_its_odometer_span_from_odometer_km(
    db_session: AsyncSession, make_closed_drive_session
):
    """The recompute reads the window's odometer keys by the same scan. The
    distance still comes from the sources it always did (none here), so a key
    newly called an odometer doesn't move `distance_km`. Red on 7210744c."""
    vin, device_id, session = await make_closed_drive_session(P, "3", distance_km=None)
    inside = session.started_at + timedelta(minutes=2)
    db_session.add_all(
        [
            _raw(vin, device_id, "ODOMETER_KM", 80000.0, inside),
            _raw(vin, device_id, "ODOMETER_KM", 80012.0, inside + timedelta(minutes=5)),
        ]
    )
    await db_session.flush()

    await SessionService(db_session).refresh_aggregates(session)

    assert (session.start_odometer, session.end_odometer) == (80000.0, 80012.0)
    assert session.distance_km is None


async def test_trip_counters_are_still_not_odometers(
    db_session: AsyncSession, make_livelink_vehicle, make_closed_drive_session
):
    """Regression guard: the exact set kept these out, and the scan does too.
    Kills a scan that takes `DISTANCE`."""
    from app.utils.odometer_units import is_converted_odometer_key

    assert not any(is_converted_odometer_key(key) for key in TRIP_COUNTERS)

    vin, device = await make_livelink_vehicle(P, "4")
    now = utc_now()
    for key in TRIP_COUNTERS:
        db_session.add(_raw(vin, device.device_id, key, 5000.0, now))
        db_session.add(
            VehicleTelemetryLatest(
                vin=vin, param_key=key, value=5000.0, timestamp=now, received_at=now
            )
        )
    await db_session.flush()

    assert await LiveLinkService(db_session).device_has_odometer_history(device) is False
    started = await SessionService(db_session).start_session(device, now)
    assert started.start_odometer is None


# --- Fix round 3 (ruling FW-A-r3): the question is kind-aware -------------------


@pytest.mark.parametrize(
    ("kind", "key"), [("torque", "TORQUE_ODOMETER"), ("generic_mqtt", "TOTAL_ODO")]
)
async def test_an_undeclared_non_wican_key_is_not_odometer_history(
    db_session: AsyncSession, make_livelink_vehicle, kind: str, key: str
):
    """Only a WiCAN records by the scan; Torque and generic MQTT record just
    their declared key, so an undeclared one has no odometer history and can
    still choose its unit and key. Red on 4e32c6eb (N1)."""
    vin, device = await make_livelink_vehicle(P, f"5{kind[0]}", kind=kind)
    db_session.add(_raw(vin, device.device_id, key, 80000.0, utc_now()))
    await db_session.flush()

    assert await LiveLinkService(db_session).device_has_odometer_history(device) is False


async def test_a_declared_non_wican_key_is_odometer_history(
    db_session: AsyncSession, make_livelink_vehicle
):
    """Regression guard: once declared, that key is the device's odometer.
    Kills a kind-aware rule that ignores the declaration."""
    vin, device = await make_livelink_vehicle(
        P, "6", kind="torque", odometer_param_key="TORQUE_ODOMETER"
    )
    db_session.add(_raw(vin, device.device_id, "TORQUE_ODOMETER", 80000.0, utc_now()))
    await db_session.flush()

    assert await LiveLinkService(db_session).device_has_odometer_history(device) is True


async def test_an_undeclared_torque_session_gets_no_odometer(
    db_session: AsyncSession, make_livelink_vehicle, make_closed_drive_session
):
    """`resolve_torque_session` leaves a Torque trip's odometer unset, and
    nothing Torque sends is its odometer until it's declared. Red on
    4e32c6eb, which stamped both from `TORQUE_ODOMETER` (N1)."""
    from sqlalchemy import select

    from app.models.livelink_device import LiveLinkDevice

    vin, device_id, session = await make_closed_drive_session(P, "7", distance_km=None)
    device = (
        await db_session.execute(
            select(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id)
        )
    ).scalar_one()
    device.kind = "torque"
    inside = session.started_at + timedelta(minutes=2)
    db_session.add_all(
        [
            _raw(vin, device_id, "TORQUE_ODOMETER", 80000.0, inside),
            _raw(vin, device_id, "TORQUE_ODOMETER", 80012.0, inside + timedelta(minutes=5)),
            VehicleTelemetryLatest(
                vin=vin,
                param_key="TORQUE_ODOMETER",
                value=80012.0,
                timestamp=inside,
                received_at=inside,
            ),
        ]
    )
    await db_session.flush()

    await SessionService(db_session).refresh_aggregates(session)
    assert (session.start_odometer, session.end_odometer) == (None, None)

    started = await SessionService(db_session).start_session(device, utc_now())
    assert started.start_odometer is None


# --- Fix round 4 (ruling FW-A-r4a): a WiCAN never takes another source's key ----

TORQUE_KEY = "TORQUE_ODOMETER"
#: Well before any row below, so the history guard's `created_at` bound sees them.
ADDED = (utc_now() - timedelta(days=10)).replace(microsecond=0)


async def _torque_phone(db: AsyncSession, vin: str, suffix: str, at) -> LiveLinkDevice:
    """A Torque phone on the same car, declaring its own total, with history under it."""
    phone = LiveLinkDevice(
        device_id=f"{P}phone{suffix:0>4}",
        vin=vin,
        enabled=True,
        kind="torque",
        odometer_param_key=TORQUE_KEY,
        created_at=ADDED,
    )
    db.add(phone)
    db.add(_raw(vin, phone.device_id, TORQUE_KEY, 80123.0, at))
    db.add(
        VehicleTelemetryLatest(
            vin=vin, param_key=TORQUE_KEY, value=80123.0, timestamp=at, received_at=at
        )
    )
    await db.flush()
    return phone


def test_the_wican_scan_skips_another_sources_own_keys():
    """The scan takes `TORQUE_ODOMETER` (it holds `ODOMETER`), but the key is
    Torque's own, from its pid map, so a WiCAN never recorded it. Declared, it
    still counts: the declaration wins everywhere. Red on 63640d97 for the
    first line; the rest are regression guards."""
    assert is_recorded_odometer_key(TORQUE_KEY, "wican") is False
    assert is_recorded_odometer_key(TORQUE_KEY, "wican", TORQUE_KEY) is True
    assert is_recorded_odometer_key(TORQUE_KEY, "torque", TORQUE_KEY) is True
    assert is_recorded_odometer_key("ODOMETER_KM", "wican") is True


async def test_a_wican_session_does_not_start_on_the_torque_phones_total(
    db_session: AsyncSession, make_livelink_vehicle
):
    """The latest table is per vehicle, so on a car with both, the WiCAN's
    start odometer came from the phone's drifting total. Red on 63640d97
    (80123.0)."""
    vin, wican = await make_livelink_vehicle(P, "8", created_at=ADDED)
    now = utc_now()
    await _torque_phone(db_session, vin, "8", now)

    session = await SessionService(db_session).start_session(wican, now)

    assert session.start_odometer is None


async def test_a_wicans_unit_guard_does_not_see_the_torque_phones_history(
    db_session: AsyncSession, make_livelink_vehicle
):
    """The phone's `TORQUE_ODOMETER` rows are its history, not the WiCAN's, so
    the WiCAN can still choose its unit. Red on 63640d97 (409)."""
    vin, wican = await make_livelink_vehicle(P, "9", created_at=ADDED)
    phone = await _torque_phone(db_session, vin, "9", utc_now())

    service = LiveLinkService(db_session)
    assert await service.device_has_odometer_history(wican) is False
    assert await service.device_has_odometer_history(phone) is True
    await service.update_device(wican.device_id, {"odometer_unit": "mi"})
    assert wican.odometer_unit == "mi"


async def test_a_wicans_own_odometer_km_still_counts_beside_a_torque_phone(
    db_session: AsyncSession, make_livelink_vehicle
):
    """Regression guard: only the other source's own keys are skipped. Kills
    an exclusion that reads the vocabulary the wrong way round."""
    vin, wican = await make_livelink_vehicle(P, "10", created_at=ADDED)
    now = utc_now()
    await _torque_phone(db_session, vin, "10", now - timedelta(minutes=1))
    db_session.add(
        VehicleTelemetryLatest(
            vin=vin, param_key="ODOMETER_KM", value=80456.0, timestamp=now, received_at=now
        )
    )
    await db_session.flush()

    assert await LiveLinkService(db_session).device_has_odometer_history(wican) is True
    session = await SessionService(db_session).start_session(wican, now)
    assert session.start_odometer == 80456.0

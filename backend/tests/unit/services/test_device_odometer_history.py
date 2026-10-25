"""One odometer-history predicate for the unit guards and the R12 exception (T7).

`_has_odometer_history` read only `vehicle_telemetry`, which
`prune_old_telemetry` empties after 90 days, so a device parked past retention
lost its guard (Fable F3-1). `device_has_odometer_history` also reads the two
tables that survive pruning, bounded by the device's `created_at` so a
replacement dongle isn't blocked by a dead one's history (Fable F4-2).

`created_at` is set EXPLICITLY on every device and record here: SQLite's
`CURRENT_TIMESTAMP` is second-resolution text, so insert order alone flakes
against a microsecond timestamp (Fable F5-4).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_device_unit import LiveLinkDeviceUnit
from app.models.odometer import OdometerRecord
from app.models.vehicle_telemetry import VehicleTelemetry, VehicleTelemetryLatest
from app.services.device_units import DeviceUnitService
from app.services.livelink_service import LiveLinkService
from app.services.livelink_sources.base import Reading, WireUnit
from app.utils.datetime_utils import utc_now

pytestmark = pytest.mark.asyncio

P = "t7hist"

#: Well clear of the second-resolution trap, on both sides.
CREATED = (utc_now() - timedelta(days=200)).replace(microsecond=0)
BEFORE = CREATED - timedelta(days=30)
AFTER = CREATED + timedelta(days=30)


async def _device(
    db: AsyncSession, make_livelink_vehicle, suffix: str, **fields: object
) -> tuple[str, LiveLinkDevice]:
    vin, device = await make_livelink_vehicle(P, suffix, created_at=CREATED, **fields)
    await db.flush()
    return vin, device


def _latest(vin: str, key: str, at: datetime) -> VehicleTelemetryLatest:
    return VehicleTelemetryLatest(
        vin=vin, param_key=key, value=80000.0, timestamp=at, received_at=at
    )


def _record(vin: str, source: str, created: datetime) -> OdometerRecord:
    return OdometerRecord(
        vin=vin, date=created.date(), odometer_km=80000, source=source, created_at=created
    )


def _raw(vin: str, device_id: str, key: str, at: datetime) -> VehicleTelemetry:
    return VehicleTelemetry(
        vin=vin, device_id=device_id, param_key=key, value=80000.0, timestamp=at, received_at=at
    )


async def _has(db: AsyncSession, device: LiveLinkDevice) -> bool:
    return await LiveLinkService(db).device_has_odometer_history(device)


# --- The predicate -----------------------------------------------------------


async def test_a_pruned_device_with_a_latest_odometer_row_has_history(
    db_session: AsyncSession, make_livelink_vehicle
):
    """The latest-value row is never pruned."""
    vin, device = await _device(db_session, make_livelink_vehicle, "01", odometer_unit="mi")
    db_session.add(_latest(vin, "ODOMETER", AFTER))
    await db_session.flush()

    assert await _has(db_session, device) is True
    with pytest.raises(ValueError, match="since this one was added"):
        await LiveLinkService(db_session).update_device(device.device_id, {"odometer_unit": "km"})


async def test_a_pruned_device_with_a_livelink_odometer_record_has_history(
    db_session: AsyncSession, make_livelink_vehicle
):
    """Nor are odometer records."""
    vin, device = await _device(db_session, make_livelink_vehicle, "02", odometer_unit="mi")
    db_session.add(_record(vin, "livelink", AFTER))
    await db_session.flush()

    assert await _has(db_session, device) is True
    with pytest.raises(ValueError, match="since this one was added"):
        await LiveLinkService(db_session).update_device(device.device_id, {"odometer_unit": "km"})


async def test_the_parameter_guard_reads_the_same_predicate(
    db_session: AsyncSession, make_livelink_vehicle
):
    """`update_device`'s second guard: changing which key is the odometer."""
    vin, device = await _device(db_session, make_livelink_vehicle, "03")
    db_session.add(_latest(vin, "A6-ODOMETER", AFTER))
    await db_session.flush()

    with pytest.raises(ValueError, match="already"):
        await LiveLinkService(db_session).update_device(
            device.device_id, {"odometer_param_key": "ODOMETER"}
        )


async def test_evidence_from_before_the_device_was_added_does_not_count(
    db_session: AsyncSession, make_livelink_vehicle
):
    """A replacement WiCAN on a VIN with a dead device's history can still pick
    its unit (Fable F4-2). Passes on main, which reads raw rows only; red
    against the plain VIN-scope predicate."""
    vin, device = await _device(db_session, make_livelink_vehicle, "04", odometer_unit="mi")
    db_session.add_all([_latest(vin, "ODOMETER", BEFORE), _record(vin, "livelink", BEFORE)])
    await db_session.flush()

    assert await _has(db_session, device) is False
    updated = await LiveLinkService(db_session).update_device(
        device.device_id, {"odometer_unit": "km"}
    )
    assert updated is not None and updated.odometer_unit == "km"


async def test_a_record_of_another_source_is_not_odometer_history(
    db_session: AsyncSession, make_livelink_vehicle
):
    """Regression guard: a fuel or manual entry is not this device's reading."""
    vin, device = await _device(db_session, make_livelink_vehicle, "05")
    db_session.add_all([_record(vin, "manual", AFTER), _record(vin, "fuel", AFTER)])
    await db_session.flush()

    assert await _has(db_session, device) is False


async def test_a_latest_row_of_a_non_odometer_key_is_not_history(
    db_session: AsyncSession, make_livelink_vehicle
):
    """Regression guard: a trip counter isn't an odometer (the exact-set rule)."""
    vin, device = await _device(db_session, make_livelink_vehicle, "06")
    db_session.add(_latest(vin, "31-DISTANCESINCECODECLEAR", AFTER))
    await db_session.flush()

    assert await _has(db_session, device) is False


async def test_the_latest_branch_keeps_the_declared_key_rule(
    db_session: AsyncSession, make_livelink_vehicle
):
    """A declared `odometer_param_key` replaces name matching on every branch."""
    vin, device = await _device(
        db_session, make_livelink_vehicle, "07", odometer_param_key="TORQUE_ODOMETER"
    )
    db_session.add(_latest(vin, "TORQUE_ODOMETER", AFTER))
    await db_session.flush()

    assert await _has(db_session, device) is True


async def test_raw_odometer_telemetry_is_history(db_session: AsyncSession, make_livelink_vehicle):
    """Regression guard: the branch main already had."""
    vin, device = await _device(db_session, make_livelink_vehicle, "08")
    db_session.add(_raw(vin, device.device_id, "ODOMETER", AFTER))
    await db_session.flush()

    assert await _has(db_session, device) is True


# --- The R12 exception -------------------------------------------------------


async def test_a_wire_declaration_keeps_a_legacy_row_on_a_pruned_device(
    db_session: AsyncSession, make_livelink_vehicle
):
    """Legacy rows only exist after migration 133, and the device most likely
    to have one is a pruned one. T3's stand-in read raw rows only."""
    vin, device = await _device(db_session, make_livelink_vehicle, "09")
    db_session.add_all(
        [
            LiveLinkDeviceUnit(
                device_id=device.device_id,
                param_key="ODOMETER",
                unit="mi",
                param_class="distance",
                source="legacy",
            ),
            _latest(vin, "ODOMETER", AFTER),
        ]
    )
    await db_session.flush()

    await DeviceUnitService(db_session).record(
        device, {"ODOMETER": WireUnit("km", "distance")}, whole_profile=True
    )

    rows = (
        await db_session.execute(
            select(LiveLinkDeviceUnit.unit, LiveLinkDeviceUnit.source).where(
                LiveLinkDeviceUnit.device_id == device.device_id
            )
        )
    ).all()
    assert [tuple(r) for r in rows] == [("mi", "legacy")]


async def test_a_wire_declaration_replaces_a_legacy_row_without_history(
    db_session: AsyncSession, make_livelink_vehicle
):
    """Regression guard: with nothing recorded under the old reading, the
    device's own declaration wins."""
    vin, device = await _device(db_session, make_livelink_vehicle, "10")
    db_session.add_all(
        [
            LiveLinkDeviceUnit(
                device_id=device.device_id,
                param_key="ODOMETER",
                unit="mi",
                param_class="distance",
                source="legacy",
            ),
            _latest(vin, "ODOMETER", BEFORE),
        ]
    )
    await db_session.flush()

    await DeviceUnitService(db_session).record(
        device, {"ODOMETER": WireUnit("km", "distance")}, whole_profile=True
    )

    rows = (
        await db_session.execute(
            select(LiveLinkDeviceUnit.unit, LiveLinkDeviceUnit.source).where(
                LiveLinkDeviceUnit.device_id == device.device_id
            )
        )
    ).all()
    assert [tuple(r) for r in rows] == [("km", "wire")]


async def test_a_kept_legacy_row_beats_the_unit_in_the_same_request(
    db_session: AsyncSession, make_livelink_vehicle
):
    """The boot POST that declared km carries km on its own readings too. Once
    `record` has kept the legacy row, that reading must still read miles, or
    the boot frame alone lands one reading below the floor."""
    _vin, device = await _device(db_session, make_livelink_vehicle, "11")
    db_session.add(
        LiveLinkDeviceUnit(
            device_id=device.device_id,
            param_key="ODOMETER",
            unit="mi",
            param_class="distance",
            source="legacy",
        )
    )
    await db_session.flush()

    (resolved,) = await DeviceUnitService(db_session).resolve_readings(
        device.device_id, [Reading("ODOMETER", 50000.0, unit="km", param_class="distance")]
    )
    assert resolved.unit == "mi"


# --- One clock (Fable F5-6) and the 409 text ----------------------------------


async def test_created_at_comes_from_the_app_clock(db_session: AsyncSession, make_livelink_vehicle):
    """The bound compares `created_at` with `vehicle_telemetry_latest.timestamp`,
    which is naive UTC from the app, so both come from `utc_now`. The server
    default gave SQLite's second-resolution `CURRENT_TIMESTAMP` (which sorts
    before the same instant from the app) and, on a PG server whose `timezone`
    isn't UTC, local time."""
    before = utc_now()
    vin, device = await make_livelink_vehicle(P, "12")
    record = OdometerRecord(vin=vin, date=date.today(), odometer_km=1, source="livelink")
    db_session.add(record)
    await db_session.flush()
    after = utc_now()

    for obj in (device, record):
        stamped = obj.__dict__.get("created_at")
        assert isinstance(stamped, datetime), type(obj).__name__
        assert stamped.tzinfo is None
        assert before <= stamped <= after


async def test_the_unit_409_names_no_tool_for_the_reverse_case(
    db_session: AsyncSession, make_livelink_vehicle
):
    """The normalise tools convert raw miles to km only, so the message can't
    send a legacy-miles-but-really-km device to them (Fable F3-8)."""
    vin, device = await _device(db_session, make_livelink_vehicle, "13", odometer_unit="mi")
    db_session.add(_raw(vin, device.device_id, "ODOMETER", AFTER))
    await db_session.flush()

    with pytest.raises(ValueError) as exc:
        await LiveLinkService(db_session).update_device(device.device_id, {"odometer_unit": "km"})
    message = str(exc.value)
    assert "this device, or another device on this vehicle since this one was added" in message
    assert "before the v2.26 conversion" in message
    assert "manual repair" in message

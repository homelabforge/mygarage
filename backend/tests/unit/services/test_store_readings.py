"""store_readings must reproduce BOTH pre-existing storage behaviors exactly.

Every test seeds its OWN vehicle and device via `make_livelink_vehicle`
(tests/unit/services/conftest.py) and filters every query by that VIN. The
suite shares one database with no per-test rollback: `init_test_db` is
session-scoped and `db_session` never rolls back (tests/conftest.py:81-97).
An unfiltered `select(...).one()` sees rows from every earlier test in this
file AND from every other suite, and a hardcoded device_id collides on the
UNIQUE index at the second test.
"""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.vehicle_telemetry import VehicleTelemetry, VehicleTelemetryLatest
from app.services.livelink_sources.base import Reading, StoragePolicy
from app.services.telemetry_service import TelemetryService

TS = datetime(2026, 9, 21, 12, 0, 0)
P = "storerd"


async def _history(db, vin):
    return (
        (await db.execute(select(VehicleTelemetry).where(VehicleTelemetry.vin == vin)))
        .scalars()
        .all()
    )


async def _latest(db, vin):
    return (
        (await db.execute(select(VehicleTelemetryLatest).where(VehicleTelemetryLatest.vin == vin)))
        .scalars()
        .all()
    )


def test_store_value_is_gone():
    assert not hasattr(TelemetryService, "store_value")


@pytest.mark.asyncio
async def test_simple_policy_writes_history_and_latest(db_session, make_livelink_vehicle):
    vin, device = await make_livelink_vehicle(P, "01")
    result = await TelemetryService(db_session).store_readings(
        vin=vin,
        device_id=device.device_id,
        readings=[Reading("PROPANE_T1_LEVEL_PCT", 71.0, unit="%")],
        timestamp=TS,
        policy=StoragePolicy(),
    )
    await db_session.commit()
    assert result.stored_count == 1
    assert [(r.param_key, r.value) for r in await _history(db_session, vin)] == [
        ("PROPANE_T1_LEVEL_PCT", 71.0)
    ]
    assert [r.value for r in await _latest(db_session, vin)] == [71.0]


@pytest.mark.asyncio
async def test_latest_always_overwrites_with_an_older_reading(db_session, make_livelink_vehicle):
    """WiCAN semantics: _upsert_latest_value is unconditional."""
    vin, device = await make_livelink_vehicle(P, "02")
    svc = TelemetryService(db_session)
    p = StoragePolicy(latest="always")
    await svc.store_readings(
        vin=vin,
        device_id=device.device_id,
        readings=[Reading("X", 2.0)],
        timestamp=TS,
        policy=p,
    )
    await svc.store_readings(
        vin=vin,
        device_id=device.device_id,
        readings=[Reading("X", 1.0)],
        timestamp=TS - timedelta(hours=1),
        policy=p,
    )
    await db_session.commit()
    rows = await _latest(db_session, vin)
    assert len(rows) == 1
    assert rows[0].value == 1.0, "policy 'always' must clobber, as WiCAN does today"


@pytest.mark.asyncio
async def test_latest_if_newer_refuses_an_older_reading(db_session, make_livelink_vehicle):
    """Torque semantics: a backfilled row never clobbers a fresher live one."""
    vin, device = await make_livelink_vehicle(P, "03")
    svc = TelemetryService(db_session)
    p = StoragePolicy(latest="if_newer")
    await svc.store_readings(
        vin=vin,
        device_id=device.device_id,
        readings=[Reading("X", 2.0)],
        timestamp=TS,
        policy=p,
    )
    await svc.store_readings(
        vin=vin,
        device_id=device.device_id,
        readings=[Reading("X", 1.0)],
        timestamp=TS - timedelta(hours=1),
        policy=p,
    )
    await db_session.commit()
    rows = await _latest(db_session, vin)
    assert len(rows) == 1
    assert rows[0].value == 2.0, "policy 'if_newer' must NOT clobber"


@pytest.mark.asyncio
async def test_storage_interval_thins_history_when_applied(db_session, make_livelink_vehicle):
    vin, device = await make_livelink_vehicle(P, "04")
    svc = TelemetryService(db_session)
    await svc.auto_register_parameter("STORERD_X")
    param = await svc.get_parameter("STORERD_X")
    param.storage_interval_seconds = 300
    await db_session.flush()
    p = StoragePolicy(apply_storage_interval=True)
    await svc.store_readings(
        vin=vin,
        device_id=device.device_id,
        readings=[Reading("STORERD_X", 1.0)],
        timestamp=TS,
        policy=p,
    )
    await svc.store_readings(
        vin=vin,
        device_id=device.device_id,
        readings=[Reading("STORERD_X", 2.0)],
        timestamp=TS + timedelta(seconds=30),
        policy=p,
    )
    await db_session.commit()
    assert len(await _history(db_session, vin)) == 1, "second reading is inside the window"


@pytest.mark.asyncio
async def test_storage_interval_ignored_when_policy_says_so(db_session, make_livelink_vehicle):
    """Preserves the old Torque writer's rule: it never consulted the interval."""
    vin, device = await make_livelink_vehicle(P, "05")
    svc = TelemetryService(db_session)
    await svc.auto_register_parameter("STORERD_Y")
    param = await svc.get_parameter("STORERD_Y")
    param.storage_interval_seconds = 300
    await db_session.flush()
    p = StoragePolicy(apply_storage_interval=False)
    await svc.store_readings(
        vin=vin,
        device_id=device.device_id,
        readings=[Reading("STORERD_Y", 1.0)],
        timestamp=TS,
        policy=p,
    )
    await svc.store_readings(
        vin=vin,
        device_id=device.device_id,
        readings=[Reading("STORERD_Y", 2.0)],
        timestamp=TS + timedelta(seconds=30),
        policy=p,
    )
    await db_session.commit()
    assert len(await _history(db_session, vin)) == 2


@pytest.mark.asyncio
async def test_duplicate_timestamp_is_deduped_not_an_error(db_session, make_livelink_vehicle):
    vin, device = await make_livelink_vehicle(P, "06")
    svc = TelemetryService(db_session)
    p = StoragePolicy(apply_storage_interval=False)
    for _ in range(2):
        await svc.store_readings(
            vin=vin,
            device_id=device.device_id,
            readings=[Reading("X", 1.0)],
            timestamp=TS,
            policy=p,
        )
    await db_session.commit()
    assert len(await _history(db_session, vin)) == 1


@pytest.mark.asyncio
async def test_empty_readings_is_a_no_op(db_session, make_livelink_vehicle):
    vin, device = await make_livelink_vehicle(P, "07")
    result = await TelemetryService(db_session).store_readings(
        vin=vin,
        device_id=device.device_id,
        readings=[],
        timestamp=TS,
        policy=StoragePolicy(),
    )
    assert result.stored_count == 0
    assert await _history(db_session, vin) == []


@pytest.mark.asyncio
async def test_a_reading_name_reaches_the_registry(db_session, make_livelink_vehicle):
    vin, device = await make_livelink_vehicle(P, "21")
    key = f"STORERD_NAMED_{uuid.uuid4().hex[:6].upper()}"
    svc = TelemetryService(db_session)
    await svc.store_readings(
        vin=vin,
        device_id=device.device_id,
        readings=[Reading(key, 1.0, display_name="Readable name")],
        timestamp=TS,
        policy=StoragePolicy(latest="if_newer", apply_storage_interval=False),
    )
    assert (await svc.get_parameter(key)).display_name == "Readable name"


@pytest.mark.asyncio
async def test_the_odometer_rebuild_keeps_the_name(db_session, make_livelink_vehicle):
    """store_readings rebuilds a declared odometer's reading in km; the name rides along."""
    key = f"STORERD_ODO_{uuid.uuid4().hex[:6].upper()}"
    vin, device = await make_livelink_vehicle(
        P, "22", kind="torque", odometer_param_key=key, odometer_unit="km"
    )
    svc = TelemetryService(db_session)
    await svc.store_readings(
        vin=vin,
        device_id=device.device_id,
        readings=[Reading(key, 1000.0, display_name="Readable odometer")],
        timestamp=TS,
        policy=StoragePolicy(latest="if_newer", apply_storage_interval=False),
        device=device,
    )
    assert (await svc.get_parameter(key)).display_name == "Readable odometer"

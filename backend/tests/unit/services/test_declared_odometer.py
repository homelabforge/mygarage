"""A device declares which parameter is its odometer; both predicates honour it.

Name matching does not generalise, and only a WiCAN records by it: a
Torque-only user got zero odometer records until a key was declared. A
declaration REPLACES the matching rather than widening it.

Every test seeds its own vehicle and device via `make_livelink_vehicle` and
filters every query by that VIN: the suite shares one database with no per-test
rollback.
"""

import pytest
from sqlalchemy import select

from app.models.odometer import OdometerRecord
from app.models.vehicle_telemetry import VehicleTelemetry
from app.services.livelink_sources.base import Capability, Reading, StoragePolicy
from app.services.livelink_sources.torque import TorqueModule
from app.services.telemetry_service import TelemetryService
from app.services.torque_pid_map import parse_torque_query
from app.utils.datetime_utils import utc_now
from app.utils.odometer_units import is_odometer_param_key

P = "declodo"
TORQUE_POLICY = StoragePolicy(latest="if_newer", apply_storage_interval=False)


async def _records(db, vin: str):
    return (
        (await db.execute(select(OdometerRecord).where(OdometerRecord.vin == vin))).scalars().all()
    )


async def _store(db, vin, device, key, value, policy=TORQUE_POLICY):
    await TelemetryService(db).store_readings(
        vin=vin,
        device_id=device.device_id,
        readings=[Reading(key, value)],
        timestamp=utc_now(),
        policy=policy,
        device=device,
    )
    await db.commit()


def test_torque_declares_the_capability_but_not_the_sync_policy():
    """sync_odometer would route storage through store_telemetry and replace
    Torque's newer-only latest write with an unconditional one."""
    assert Capability.ODOMETER in TorqueModule.capabilities
    assert TorqueModule.storage_policy.sync_odometer is False
    assert TorqueModule.storage_policy.latest == "if_newer"


def test_the_torque_odometer_pid_maps_to_a_stable_key():
    assert parse_torque_query({"kff120c": "90170.0"}).obd["TORQUE_ODOMETER"] == 90170.0


def test_the_strict_predicate_rejects_the_torque_key_without_a_declaration():
    """Guards the trip-counter reasoning behind the exact-set _ODOMETER_BARE_KEYS."""
    assert is_odometer_param_key("TORQUE_ODOMETER") is False
    assert is_odometer_param_key("A6-ODOMETER") is True


def test_a_declaration_overrides_the_predicate():
    assert is_odometer_param_key("TORQUE_ODOMETER", declared="TORQUE_ODOMETER") is True
    assert is_odometer_param_key("KFF1234", declared="KFF1234") is True
    assert is_odometer_param_key("SPEED", declared="TORQUE_ODOMETER") is False


def test_a_declaration_does_not_widen_matching_for_other_keys():
    """A trip counter must not become an odometer because one is declared."""
    assert is_odometer_param_key("21-DISTANCEMILON", declared="TORQUE_ODOMETER") is False


@pytest.mark.asyncio
async def test_no_record_when_the_device_declares_nothing(db_session, make_livelink_vehicle):
    """Existing installs must see zero behaviour change."""
    vin, device = await make_livelink_vehicle(P, "01", kind="torque")
    assert device.odometer_param_key is None
    await _store(db_session, vin, device, "TORQUE_ODOMETER", 90170.0)
    assert await _records(db_session, vin) == []


@pytest.mark.asyncio
async def test_a_declared_odometer_in_miles_is_stored_as_km(db_session, make_livelink_vehicle):
    """THE regression test: raw miles written as km is silent corruption."""
    vin, device = await make_livelink_vehicle(
        P, "02", kind="torque", odometer_param_key="TORQUE_ODOMETER", odometer_unit="mi"
    )
    await _store(db_session, vin, device, "TORQUE_ODOMETER", 90170.0)
    rows = await _records(db_session, vin)
    assert len(rows) == 1
    assert 145_000 < float(rows[0].odometer_km) < 145_200, "90,170 mi is ~145,114 km"


@pytest.mark.asyncio
async def test_the_raw_telemetry_row_is_also_km(db_session, make_livelink_vehicle):
    """Normalise ONCE before storage. Per-consumer conversion is the four-month bug."""
    vin, device = await make_livelink_vehicle(
        P, "03", kind="torque", odometer_param_key="TORQUE_ODOMETER", odometer_unit="mi"
    )
    await _store(db_session, vin, device, "TORQUE_ODOMETER", 90170.0)
    row = (
        (await db_session.execute(select(VehicleTelemetry).where(VehicleTelemetry.vin == vin)))
        .scalars()
        .one()
    )
    assert 145_000 < row.value < 145_200, "storage and record path must agree"


@pytest.mark.asyncio
async def test_a_non_pattern_custom_pid_in_miles_is_converted(db_session, make_livelink_vehicle):
    """Kills the dead-parameter mutant in _normalize_odometer_units.

    TORQUE_ODOMETER matches the substring scan by accident, so a declaration
    never forwarded into the normaliser body still passes every other test here.
    KFF1234 matches nothing, so this fails unless `declared` really is forwarded.
    """
    vin, device = await make_livelink_vehicle(
        P, "04", kind="torque", odometer_param_key="KFF1234", odometer_unit="mi"
    )
    await _store(db_session, vin, device, "KFF1234", 90170.0)
    row = (
        (await db_session.execute(select(VehicleTelemetry).where(VehicleTelemetry.vin == vin)))
        .scalars()
        .one()
    )
    assert 145_000 < row.value < 145_200, "90,170 mi must be stored as ~145,114 km"
    assert len(await _records(db_session, vin)) == 1


@pytest.mark.asyncio
async def test_a_parameter_other_than_the_declared_one_is_ignored(
    db_session, make_livelink_vehicle
):
    vin, device = await make_livelink_vehicle(
        P, "05", kind="torque", odometer_param_key="TORQUE_ODOMETER", odometer_unit="mi"
    )
    await _store(db_session, vin, device, "SPEED", 60.0)
    assert await _records(db_session, vin) == []


@pytest.mark.asyncio
async def test_wican_records_exactly_once(db_session, make_livelink_vehicle):
    """WiCAN normalises and records inside store_telemetry; no double-record."""
    vin, device = await make_livelink_vehicle(P, "06", kind="wican", odometer_unit="km")
    await _store(
        db_session,
        vin,
        device,
        "A6-ODOMETER",
        145_000.0,
        policy=StoragePolicy(sync_odometer=True, observe_movement=True),
    )
    assert len(await _records(db_session, vin)) == 1


@pytest.mark.asyncio
async def test_a_reading_below_the_maximum_warns_once(db_session, make_livelink_vehicle, caplog):
    """A declared odometer that never records must say so above debug level.

    For Torque's app-accumulated ff120C this is the EXPECTED steady state once
    any fuel record sits above it, so silence would mean the feature produces
    nothing and explains nothing. Throttled to once per VIN per day.
    """
    import logging

    from app.services.telemetry_service import _DECLARED_ODOMETER_WARNED

    vin, device = await make_livelink_vehicle(
        P, "07", kind="torque", odometer_param_key="TORQUE_ODOMETER", odometer_unit="km"
    )
    _DECLARED_ODOMETER_WARNED.pop(vin, None)

    await _store(db_session, vin, device, "TORQUE_ODOMETER", 200_000.0)
    with caplog.at_level(logging.WARNING):
        await _store(db_session, vin, device, "TORQUE_ODOMETER", 145_000.0)
        await _store(db_session, vin, device, "TORQUE_ODOMETER", 145_001.0)

    assert len(await _records(db_session, vin)) == 1
    warned = [r for r in caplog.records if "declared odometer" in r.message.lower()]
    assert len(warned) == 1, "warned once per VIN per day, not once per frame"

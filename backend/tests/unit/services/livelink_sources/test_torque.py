"""Torque query-string parsing, including the device-clock clamp, plus an upload
through ingest to storage."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle_telemetry import VehicleTelemetry, VehicleTelemetryLatest
from app.services.livelink_ingest import ingest
from app.services.livelink_service import LiveLinkService
from app.services.livelink_sources.base import (
    Capability,
    ExplicitSession,
    HttpEnvelope,
    MqttEnvelope,
    Reading,
)
from app.services.livelink_sources.torque import TorqueModule
from app.services.telemetry_service import TelemetryService

M = TorqueModule()


def test_declares_odometer_as_a_capability_but_not_as_a_storage_policy():
    """The capability opens the door; the DEVICE decides by naming a parameter.

    sync_odometer must stay False: it routes storage through store_telemetry,
    which would replace Torque's newer-only latest write with an unconditional
    one and undo the divergence StoragePolicy exists to preserve.
    """
    assert Capability.ODOMETER in M.capabilities
    assert M.capabilities == frozenset(
        {
            Capability.TELEMETRY,
            Capability.DRIVE_SESSION,
            Capability.LOCATION,
            Capability.ODOMETER,
        }
    )
    assert M.storage_policy.sync_odometer is False


def test_names_its_own_pids_as_its_vocabulary():
    """Its extended PIDs are Torque's alone; the standard ones map onto aliases
    a WiCAN sends too, so they're nobody's (FW-A-r4a). Red on 63640d97."""
    assert {"TORQUE_ODOMETER", "KFF1204"} <= M.own_param_keys
    assert not {"SPEED", "COOLANT_TMP"} & M.own_param_keys


def test_storage_policy_is_newer_only_with_no_odometer_or_movement():
    """The storage interval isn't a policy field: every source honours it, Torque
    included since G5b-12 (see the upload test at the bottom)."""
    assert M.storage_policy.latest == "if_newer"
    assert M.storage_policy.sync_odometer is False
    assert M.storage_policy.observe_movement is False


@pytest.mark.asyncio
async def test_ignores_an_mqtt_envelope():
    assert await M.parse(MqttEnvelope("a/b", b"1")) is None


@pytest.mark.asyncio
async def test_device_key_is_the_path_token():
    batch = await M.parse(HttpEnvelope(token="tok123", params={"session": "9"}))
    assert batch.device_key == "tok123"
    assert batch.session == ExplicitSession(external_id="9")


@pytest.mark.asyncio
async def test_a_past_device_clock_is_trusted():
    past = datetime.now(UTC) - timedelta(hours=2)
    batch = await M.parse(
        HttpEnvelope(token="t", params={"time": str(int(past.timestamp() * 1000))})
    )
    assert batch.timestamp is not None
    assert batch.timestamp < datetime.now(UTC).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_a_future_device_clock_is_clamped_to_now():
    future = datetime.now(UTC) + timedelta(days=3)
    batch = await M.parse(
        HttpEnvelope(token="t", params={"time": str(int(future.timestamp() * 1000))})
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    assert batch.timestamp <= now + timedelta(seconds=5)


@pytest.mark.asyncio
async def test_garbage_time_degrades_to_server_now_rather_than_raising():
    batch = await M.parse(HttpEnvelope(token="t", params={"time": "9" * 20}))
    assert batch.timestamp is not None


@pytest.mark.asyncio
async def test_flags_preserve_torques_current_side_effects():
    batch = await M.parse(HttpEnvelope(token="t", params={"kc": "900"}))
    assert batch.requires_link is True
    assert batch.alert_on_thresholds is False, "Torque has never sent threshold alerts"
    assert batch.clear_pending_offline is False


@pytest.mark.asyncio
async def test_gps_becomes_a_geopoint():
    batch = await M.parse(HttpEnvelope(token="t", params={"kff1006": "45.5", "kff1005": "-122.6"}))
    assert batch.location is not None
    assert float(batch.location.latitude) == pytest.approx(45.5)


@pytest.mark.asyncio
async def test_a_reading_with_data_asserts_ecu_online():
    batch = await M.parse(HttpEnvelope(token="t", params={"kc": "900"}))
    assert batch.ecu_status == "online"


@pytest.mark.asyncio
async def test_readings_carry_torques_default_unit_and_name():
    """Torque sends its default unit whatever the phone shows, so userUnit
    (here °F) never labels a value; intake pressure says kPa, so the dashboard
    stops reading it as a temperature."""
    batch = await M.parse(
        HttpEnvelope(
            token="t",
            params={
                "userUnit05": "°F",
                "k5": "91.0",
                "kb": "62.0",
                "kff1238": "14.1",
                "k33": "100.0",
            },
        )
    )
    assert batch.readings == [
        Reading("COOLANT_TMP", 91.0, unit="°C"),
        Reading("INTAKE_PRESSURE", 62.0, unit="kPa"),
        Reading("KFF1238", 14.1, unit="V", display_name="OBD adapter voltage"),
        Reading("K33", 100.0),
    ]


@pytest.mark.asyncio
async def test_a_declared_unit_that_disagrees_leaves_the_static_unit(
    db_session: AsyncSession,
) -> None:
    """TQ-L6: the value is stored in the static unit, so a unit-less row gets that
    one too, not whatever the phone declared. A key with no static unit keeps
    the declared one."""
    batch = await M.parse(
        HttpEnvelope(token="t", params={"defaultUnit05": "°F", "defaultUnit33": "kPa"})
    )
    assert batch is not None
    svc = TelemetryService(db_session)
    try:
        param = await svc.auto_register_parameter("COOLANT_TMP")
        param.unit = None
        await svc.fill_declared_units(batch.declared_units)
        assert param.unit == "°C"
    finally:
        await db_session.rollback()
    assert batch.declared_units == {"COOLANT_TMP": "°C", "K33": "kPa"}


@pytest.mark.asyncio
@pytest.mark.usefixtures("livelink_enabled")
async def test_an_upload_honours_the_parameter_storage_interval(
    db_session: AsyncSession, make_livelink_vehicle
) -> None:
    """G5b-12: two frames 5 s apart under a 60 s interval keep one history row.
    The latest value still follows the second frame; only history thins."""
    token = "tq-interval-token-g5b12"
    vin, _ = await make_livelink_vehicle(
        "tqint", "01", kind="torque", device_token_hash=LiveLinkService.hash_token(token)
    )
    svc = TelemetryService(db_session)
    param = await svc.auto_register_parameter("KFF7E01")
    param.storage_interval_seconds = 60
    await db_session.commit()

    t0 = datetime.now(UTC) - timedelta(minutes=10)
    for offset, value in ((0, "1.0"), (5, "2.0")):
        ms = int((t0 + timedelta(seconds=offset)).timestamp() * 1000)
        outcome = await ingest(
            M,
            HttpEnvelope(
                token=token, params={"session": "g5b12", "time": str(ms), "kff7e01": value}
            ),
            db_session,
        )
        await db_session.commit()
        assert outcome.device is not None, "the token must resolve, or nothing was tested"

    history = (
        (
            await db_session.execute(
                select(VehicleTelemetry.value).where(
                    VehicleTelemetry.vin == vin, VehicleTelemetry.param_key == "KFF7E01"
                )
            )
        )
        .scalars()
        .all()
    )
    assert history == [1.0]
    latest = (
        await db_session.execute(
            select(VehicleTelemetryLatest.value).where(
                VehicleTelemetryLatest.vin == vin, VehicleTelemetryLatest.param_key == "KFF7E01"
            )
        )
    ).scalar_one()
    assert latest == 2.0

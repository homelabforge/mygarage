"""Readable names for the shared canonical keys (O-T7, R3).

A new row used to get the title-cased key ("Coolant Tmp", "Engine Rpm"). It
gets the readable name now, and a row still on the old auto name moves to it
at its next upload, WiCAN or Torque. A name someone set stays.

COOLANT_TMP is shared by the whole suite, so every test here starts and ends
it from nothing.
"""

from collections.abc import AsyncGenerator
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_parameter import LiveLinkParameter
from app.services.livelink_sources.base import Reading
from app.services.livelink_sources.torque import TorqueModule
from app.services.telemetry_service import TelemetryService

TS = datetime(2026, 10, 29, 12, 0, 0)
P = "rdname"
KEY = "COOLANT_TMP"

#: The D2 table, as answered 2026-10-29.
D2 = {
    "COOLANT_TMP": "Coolant temperature",
    "ENGINE_RPM": "Engine RPM",
    "ENGINE_LOAD": "Engine load",
    "INTAKE_PRESSURE": "Intake manifold pressure",
    "INTAKE_TEMP": "Intake air temperature",
    "TIMING_ADVANCE": "Timing advance",
    "MAF": "Mass air flow",
    "THROTTLE": "Throttle position",
    "RUN_TIME": "Engine run time",
    "FUEL": "Fuel level",
    "CONTROL_MODULE_VOLTAGE": "Control module voltage",
    "AMBIENT_TEMP": "Ambient air temperature",
    "OIL_TEMP": "Engine oil temperature",
    "SPEED": "Speed",
    "TORQUE_ODOMETER": "Odometer (Torque)",
}


@pytest_asyncio.fixture
async def no_coolant_row(db_session: AsyncSession) -> AsyncGenerator[None]:
    """Start and end with no COOLANT_TMP row, so a test's own row is the one it reads."""
    await db_session.execute(delete(LiveLinkParameter).where(LiveLinkParameter.param_key == KEY))
    await db_session.commit()
    yield
    await db_session.execute(delete(LiveLinkParameter).where(LiveLinkParameter.param_key == KEY))
    await db_session.commit()


async def _seed(db_session: AsyncSession, name: str | None) -> None:
    db_session.add(LiveLinkParameter(param_key=KEY, display_name=name))
    await db_session.commit()


async def _name(db_session: AsyncSession) -> str | None:
    db_session.expire_all()
    param = await TelemetryService(db_session).get_parameter(KEY)
    assert param is not None
    return param.display_name


def test_the_table_is_d2() -> None:
    from app.constants.param_names import READABLE_PARAM_NAMES

    assert READABLE_PARAM_NAMES == D2


@pytest.mark.asyncio
async def test_a_new_row_gets_the_readable_name(db_session, no_coolant_row):
    param = await TelemetryService(db_session).auto_register_parameter(KEY)
    # main: "Coolant Tmp"
    assert param.display_name == "Coolant temperature"


@pytest.mark.asyncio
async def test_a_row_on_the_readable_name_still_takes_a_source_name(db_session, no_coolant_row):
    """The readable name is an auto name too, so a source that names the key still wins."""
    await _seed(db_session, "Coolant temperature")
    param = await TelemetryService(db_session).auto_register_parameter(
        KEY, display_name="Coolant (sensor 2)"
    )
    # main: the auto test only knew "Coolant Tmp", so this read as a set name
    assert param.display_name == "Coolant (sensor 2)"


def test_a_key_with_no_readable_name_keeps_the_title_case() -> None:
    assert TelemetryService._format_display_name("KFF9999_ZZ") == "Kff9999 Zz"
    assert TelemetryService._format_display_name("ENGINE_RPM") == "Engine RPM"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("Coolant Tmp", "Coolant temperature"),
        (None, "Coolant temperature"),
        ("My coolant", "My coolant"),
    ],
)
async def test_a_wican_upload_moves_a_registered_row_off_the_auto_name(
    db_session, no_coolant_row, make_livelink_vehicle, before, after
):
    """store_telemetry only registers new keys, so the rename needs its own pass (F6-1)."""
    await _seed(db_session, before)
    suffix = {None: "01", "Coolant Tmp": "02", "My coolant": "03"}[before]
    vin, device = await make_livelink_vehicle(P, suffix)

    await TelemetryService(db_session).store_telemetry(
        vin=vin, device_id=device.device_id, autopid_data={KEY: 88.0}, config={}, timestamp=TS
    )
    await db_session.commit()

    # main: "Coolant Tmp" and None stay where they were
    assert await _name(db_session) == after


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("Coolant Tmp", "Coolant temperature"),
        (None, "Coolant temperature"),
        ("My coolant", "My coolant"),
    ],
)
async def test_a_torque_upload_moves_a_row_off_the_auto_name(
    db_session, no_coolant_row, make_livelink_vehicle, before, after
):
    """Torque passes no name for a standard PID, so the rename falls back to the table."""
    await _seed(db_session, before)
    suffix = {None: "11", "Coolant Tmp": "12", "My coolant": "13"}[before]
    vin, device = await make_livelink_vehicle(P, suffix, kind="torque")

    await TelemetryService(db_session).store_readings(
        vin=vin,
        device_id=device.device_id,
        readings=[Reading(KEY, 88.0, unit="°C")],
        timestamp=TS,
        policy=TorqueModule.storage_policy,
    )
    await db_session.commit()

    # main: "Coolant Tmp" and None stay where they were
    assert await _name(db_session) == after

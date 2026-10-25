"""The per-device wire-unit store and the one resolution step (R12, R4).

Imported inside each test: before T3 none of this exists.
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _count(db: AsyncSession, device_id: str) -> int:
    from app.models.livelink_device_unit import LiveLinkDeviceUnit

    stmt = select(func.count()).where(LiveLinkDeviceUnit.device_id == device_id)
    return (await db.execute(stmt)).scalar_one()


async def test_a_device_holds_at_most_512_keys_and_says_so(
    db_session: AsyncSession, make_livelink_vehicle, caplog
):
    """Same cap as the in-memory map, logged as a warning: a full store locks
    new keys out until the next boot replaces it."""
    from app.services.device_units import DeviceUnitService
    from app.services.livelink_sources.base import WireUnit

    _vin, device = await make_livelink_vehicle("t3cap", "1")
    svc = DeviceUnitService(db_session)

    with caplog.at_level(logging.WARNING, logger="app.services.device_units"):
        await svc.record(
            device,
            {f"K{i:04X}": WireUnit("kPa", "pressure") for i in range(600)},
            whole_profile=False,
        )
    assert await _count(db_session, device.device_id) == 512
    assert any("88" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)

    # A key already held still updates past the cap.
    await svc.record(device, {"K0000": WireUnit("psi", None)}, whole_profile=False)
    held = await svc.units_for(device.device_id)
    assert held["K0000"] == WireUnit("psi", None)
    assert "K0200" not in held


async def test_a_new_boot_profile_frees_the_keys_it_dropped(
    db_session: AsyncSession, make_livelink_vehicle
):
    """Fable F3-3: renamed or junk keys don't fill the store for good."""
    from app.services.device_units import DeviceUnitService
    from app.services.livelink_sources.base import WireUnit

    _vin, device = await make_livelink_vehicle("t3cap", "2")
    svc = DeviceUnitService(db_session)
    await svc.record(
        device, {f"OLD{i}": WireUnit("V", "voltage") for i in range(512)}, whole_profile=True
    )

    await svc.record(device, {"NEW": WireUnit("V", "voltage")}, whole_profile=True)

    assert await svc.units_for(device.device_id) == {"NEW": WireUnit("V", "voltage")}


async def test_resolution_fills_only_what_a_reading_lacks(
    db_session: AsyncSession, make_livelink_vehicle
):
    """The reading's own unit > the device's stored row > none."""
    from app.services.device_units import DeviceUnitService
    from app.services.livelink_sources.base import Reading, WireUnit

    _vin, device = await make_livelink_vehicle("t3res", "1")
    svc = DeviceUnitService(db_session)
    await svc.record(
        device,
        {"COOLANT": WireUnit("°C", "temperature"), "BOOST": WireUnit("kPa", "pressure")},
        whole_profile=False,
    )

    out = await svc.resolve_readings(
        device.device_id,
        [
            Reading("COOLANT", 90.0),
            Reading("BOOST", 100.0, unit="psi"),
            Reading("OTHER", 1.0),
        ],
    )

    assert out == [
        Reading("COOLANT", 90.0, unit="°C", param_class="temperature"),
        Reading("BOOST", 100.0, unit="psi", param_class="pressure"),
        Reading("OTHER", 1.0),
    ]

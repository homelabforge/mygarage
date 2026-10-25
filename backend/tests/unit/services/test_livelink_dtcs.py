"""DTCs through the LiveLink pipeline (D3a, S1d-01, A-6).

The WiCAN `can/rx` parser used to drop `DIAGNOSTIC_TROUBLE_CODES` at its
numeric filter and nothing read `IngestBatch.dtcs`, so only the HTTPS route
ever recorded a code. Now the parser lifts the string into `batch.dtcs` and
ingest records it for any module that declares `Capability.DTC`.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.vehicle_dtc import VehicleDTC
from app.models.vehicle_telemetry import VehicleTelemetry
from app.services.livelink_ingest import ingest
from app.services.livelink_sources.base import Capability, IngestBatch, MqttEnvelope, Reading
from app.services.livelink_sources.registry import default_registry
from app.services.livelink_sources.wican import WicanModule

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("livelink_enabled")]

OLD = datetime(2026, 9, 1, 8, 0, 0)


def _rx(device_id: str, data: dict) -> MqttEnvelope:
    return MqttEnvelope(f"wican/{device_id}/can/rx", json.dumps(data).encode())


async def _dtcs(db: AsyncSession, vin: str) -> list[VehicleDTC]:
    stmt = select(VehicleDTC).where(VehicleDTC.vin == vin).order_by(VehicleDTC.code)
    return list((await db.execute(stmt)).scalars().all())


async def _row_keys(db: AsyncSession, device_id: str) -> set[str]:
    stmt = select(VehicleTelemetry.param_key).where(VehicleTelemetry.device_id == device_id)
    return set((await db.execute(stmt)).scalars().all())


async def test_a_can_rx_dtc_string_records_each_code_and_the_reading(
    db_session: AsyncSession, make_livelink_vehicle
):
    vin, device = await make_livelink_vehicle("dtcp", "1")
    await db_session.commit()

    await ingest(
        WicanModule(),
        _rx(device.device_id, {"DIAGNOSTIC_TROUBLE_CODES": "P0301, p0420", "ENGINE_RPM": 800}),
        db_session,
    )
    await db_session.flush()

    rows = await _dtcs(db_session, vin)
    assert [r.code for r in rows] == ["P0301", "P0420"]
    assert all(r.device_id == device.device_id and r.is_active for r in rows)
    assert await _row_keys(db_session, device.device_id) == {"ENGINE_RPM"}


async def test_a_dtc_only_frame_records_codes_and_leaves_the_ecu_alone(
    db_session: AsyncSession, make_livelink_vehicle
):
    """A code list is no proof the ECU is on, so no session and no ecu flip."""
    vin, device = await make_livelink_vehicle(
        "dtcp", "2", ecu_status="offline", device_status="offline"
    )
    await db_session.commit()

    await ingest(
        WicanModule(), _rx(device.device_id, {"DIAGNOSTIC_TROUBLE_CODES": "P0301"}), db_session
    )
    await db_session.flush()
    await db_session.refresh(device)

    assert [r.code for r in await _dtcs(db_session, vin)] == ["P0301"]
    assert device.ecu_status == "offline"
    assert device.device_status == "online"
    sessions = select(DriveSession).where(DriveSession.device_id == device.device_id)
    assert (await db_session.execute(sessions)).scalars().all() == []


async def test_a_code_listed_twice_in_one_frame_is_one_row(
    db_session: AsyncSession, make_livelink_vehicle
):
    """Regression guard on `process_dtcs` (unchanged): a repeat in one call reuses the row.

    `_create_vehicle_dtc` flushes, so the second lookup finds the first row.
    The parser dedupes too (`test_the_dtc_string_rule`), so this guards
    the service's own behaviour if that ever goes. Red on main only because
    main never reached `process_dtcs` from MQTT.
    """
    vin, device = await make_livelink_vehicle("dtcp", "3")
    await db_session.commit()

    await ingest(
        WicanModule(),
        _rx(device.device_id, {"DIAGNOSTIC_TROUBLE_CODES": "P0301,p0301 ", "ENGINE_RPM": 800}),
        db_session,
    )
    await db_session.flush()

    assert [r.code for r in await _dtcs(db_session, vin)] == ["P0301"]


async def test_the_same_code_in_a_later_frame_bumps_last_seen_not_a_new_row(
    db_session: AsyncSession, make_livelink_vehicle
):
    """Regression guard on `process_dtcs` (unchanged): an active row is reused.

    Red on main anyway, since main never reaches `process_dtcs` from MQTT.
    """
    vin, device = await make_livelink_vehicle("dtcp", "4")
    await db_session.commit()
    frame = {"DIAGNOSTIC_TROUBLE_CODES": "P0301", "ENGINE_RPM": 800}

    await ingest(WicanModule(), _rx(device.device_id, frame), db_session)
    await db_session.flush()
    (first,) = await _dtcs(db_session, vin)
    first.last_seen = OLD
    await db_session.commit()

    await ingest(WicanModule(), _rx(device.device_id, frame), db_session)
    await db_session.flush()

    rows = await _dtcs(db_session, vin)
    assert len(rows) == 1
    assert rows[0].id == first.id
    assert rows[0].last_seen > OLD


async def test_a_module_without_the_dtc_capability_records_no_codes(
    db_session: AsyncSession, make_livelink_vehicle, monkeypatch: pytest.MonkeyPatch
):
    """Regression guard (structural): the step is gated on `Capability.DTC`.

    No non-DTC module fills `dtcs` from a wire payload, so the real generic
    module's `parse` is patched to hand one over (Fable F1-7).
    """
    module = default_registry().get_module("generic_mqtt")
    assert module is not None
    assert Capability.DTC not in module.capabilities
    vin, device = await make_livelink_vehicle("dtcp", "5", kind="generic_mqtt")
    await db_session.commit()

    async def parse(env) -> IngestBatch:
        return IngestBatch(
            device_key=device.device_id,
            readings=[Reading("DTCP_LEVEL", 42.0)],
            dtcs=["P0301"],
        )

    monkeypatch.setattr(module, "parse", parse)

    await ingest(module, MqttEnvelope("dtcp/test/level", b"42"), db_session)
    await db_session.flush()

    assert await _dtcs(db_session, vin) == []
    # The batch did get through, so the empty list above is the gate's doing.
    assert await _row_keys(db_session, device.device_id) == {"DTCP_LEVEL"}

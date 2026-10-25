"""NaN and infinity never reach storage, from any source (A-3, Fable F1-6).

`json.loads` takes `NaN`/`Infinity` literals and `float()` takes "nan"/"inf",
so a WiCAN frame, an HTTPS payload or a generic topic could all carry one. On
SQLite a NaN binds as NULL and `vehicle_telemetry_latest.value` is NOT NULL, so
every such message raised an IntegrityError and took its good values down too.
The last test is the empty-frame twin (A-7): a frame with no value at all.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_topic_map import LiveLinkTopicMap
from app.models.vehicle_telemetry import VehicleTelemetry, VehicleTelemetryLatest
from app.services.livelink_ingest import ingest
from app.services.livelink_sources.base import (
    BaseSourceModule,
    Capability,
    IngestBatch,
    MqttEnvelope,
    Reading,
    StoragePolicy,
)
from app.services.livelink_sources.generic_mqtt import GenericMqttModule
from app.services.livelink_sources.wican import WicanModule

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("livelink_enabled")]


async def _row_keys(db: AsyncSession, device_id: str) -> set[str]:
    stmt = select(VehicleTelemetry.param_key).where(VehicleTelemetry.device_id == device_id)
    return set((await db.execute(stmt)).scalars().all())


async def _latest_keys(db: AsyncSession, vin: str) -> set[str]:
    stmt = select(VehicleTelemetryLatest.param_key).where(VehicleTelemetryLatest.vin == vin)
    return set((await db.execute(stmt)).scalars().all())


class _NanSource(BaseSourceModule):
    """A source whose parser lets a NaN through: the pipeline is the backstop."""

    kind = "nansource"
    capabilities = frozenset({Capability.TELEMETRY})
    storage_policy = StoragePolicy()

    def __init__(self, device_id: str) -> None:
        self.device_id = device_id

    async def parse(self, env):
        return IngestBatch(
            device_key=self.device_id,
            readings=[
                Reading("NANSRC_BAD", float("nan")),
                Reading("NANSRC_HOT", float("inf")),
                Reading("NANSRC_GOOD", 1.5),
            ],
        )


async def test_the_pipeline_drops_a_non_finite_reading_from_any_source(
    db_session: AsyncSession, make_livelink_vehicle
):
    vin, device = await make_livelink_vehicle("nanp", "1", kind="nansource")
    await db_session.commit()

    await ingest(_NanSource(device.device_id), MqttEnvelope("t", b"x"), db_session)
    await db_session.flush()

    assert await _row_keys(db_session, device.device_id) == {"NANSRC_GOOD"}
    assert await _latest_keys(db_session, vin) == {"NANSRC_GOOD"}


async def test_a_wican_can_rx_nan_stores_the_rest_of_the_frame(
    db_session: AsyncSession, make_livelink_vehicle
):
    vin, device = await make_livelink_vehicle("nanw", "1")
    await db_session.commit()

    await ingest(
        WicanModule(),
        MqttEnvelope(f"wican/{device.device_id}/can/rx", b'{"SPEED": NaN, "ENGINE_RPM": 800}'),
        db_session,
    )
    await db_session.flush()

    assert await _row_keys(db_session, device.device_id) == {"ENGINE_RPM"}
    assert "SPEED" not in await _latest_keys(db_session, vin)


async def test_an_https_payload_nan_stores_the_rest_of_the_payload(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle
):
    """The route calls store_telemetry itself until T3 moves it onto ingest.

    Raw content, not `json=`: httpx refuses to encode NaN, a WiCAN does not.
    """
    vin, device = await make_livelink_vehicle("nanh", "1")
    await db_session.commit()
    # json.dumps writes the NaN and Infinity literals a WiCAN would send.
    body = json.dumps(
        {
            "autopid_data": {
                "SPEED": float("nan"),
                "COOLANT_TEMP": float("inf"),
                "ENGINE_RPM": 800,
            },
            "config": {},
            "status": {"device_id": device.device_id, "ecu_status": "online"},
        }
    )

    with patch("app.routes.livelink.validate_livelink_token", new_callable=AsyncMock) as validate:
        validate.return_value = True
        response = await client.post(
            "/api/v1/livelink/ingest",
            content=body,
            headers={"Authorization": "Bearer t", "Content-Type": "application/json"},
        )

    assert response.status_code == 202
    assert "processing_error" not in response.json()
    assert await _row_keys(db_session, device.device_id) == {"ENGINE_RPM"}
    assert {"SPEED", "COOLANT_TEMP"}.isdisjoint(await _latest_keys(db_session, vin))


NAN_T = "nonfinite/test/tank1/level_percent"


@pytest_asyncio.fixture
async def generic(db_session: AsyncSession, make_livelink_vehicle, request):
    """A linked generic sensor, one per test (parametrized ids included)."""
    suffix = f"{abs(hash(request.node.name)) % 10**6:06d}"
    vin, device = await make_livelink_vehicle("nang", suffix, kind="generic_mqtt")
    await db_session.execute(delete(LiveLinkTopicMap).where(LiveLinkTopicMap.topic == NAN_T))
    db_session.add(
        LiveLinkTopicMap(device_id=device.device_id, topic=NAN_T, param_key="NANG_T1_LEVEL_PCT")
    )
    await db_session.commit()
    module = GenericMqttModule()
    await module.refresh(db_session)

    device_id = device.device_id  # read now: the rollback below expires it
    yield vin, device, module

    await db_session.rollback()
    await db_session.execute(
        delete(LiveLinkTopicMap).where(LiveLinkTopicMap.device_id == device_id)
    )
    await db_session.commit()


@pytest.mark.parametrize("payload", [b"nan", b"inf", b"-inf", b"1e400"])
async def test_a_published_non_finite_value_stores_nothing_and_raises_nothing(
    db_session: AsyncSession, generic, payload: bytes
):
    vin, device, module = generic

    await ingest(module, MqttEnvelope(NAN_T, payload), db_session)
    await db_session.flush()

    assert await _row_keys(db_session, device.device_id) == set()
    assert await _latest_keys(db_session, vin) == set()


async def test_a_can_rx_with_no_value_leaves_the_ecu_alone(
    db_session: AsyncSession, make_livelink_vehicle
):
    """A-7: `{"X": null}` is a frame with nothing in it, not proof the ECU is on."""
    vin, device = await make_livelink_vehicle("nanw", "2", ecu_status="offline")
    await db_session.commit()

    await ingest(
        WicanModule(),
        MqttEnvelope(f"wican/{device.device_id}/can/rx", b'{"X": null}'),
        db_session,
    )
    await db_session.flush()
    await db_session.refresh(device)

    assert device.ecu_status == "offline"

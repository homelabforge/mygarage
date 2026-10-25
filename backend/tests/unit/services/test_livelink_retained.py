"""Retained MQTT messages through the real pipeline (R1, A-2, N-3).

A retained message is the broker replaying the last value it holds, of unknown
age. WiCAN publishes `can/rx` retained and rv-gateway retains every topic, so
each reconnect used to restamp a dead device's last frame as fresh: a row, a
latest value, a movement sample, `last_seen=now` and a green card. The one
retained message still applied is a status topic's own `offline` (an LWT).
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_topic_map import LiveLinkTopicMap
from app.models.vehicle_telemetry import VehicleTelemetry, VehicleTelemetryLatest
from app.services.livelink_ingest import ingest
from app.services.livelink_integrations import device_is_online
from app.services.livelink_sources.base import MqttEnvelope
from app.services.livelink_sources.generic_mqtt import GenericMqttModule
from app.services.livelink_sources.wican import WicanModule
from app.utils.datetime_utils import utc_now

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("livelink_enabled")]

#: Long enough ago that `device_is_online`'s last_seen window has lapsed.
OLD = datetime(2026, 9, 1, 8, 0, 0)
TIMEOUT_MINUTES = 10


def _retained(topic: str, payload: bytes) -> MqttEnvelope:
    return MqttEnvelope(topic=topic, payload=payload, retain=True)


async def _rows(db: AsyncSession, device_id: str) -> list[VehicleTelemetry]:
    stmt = select(VehicleTelemetry).where(VehicleTelemetry.device_id == device_id)
    return list((await db.execute(stmt)).scalars().all())


async def _latest(db: AsyncSession, vin: str) -> list[VehicleTelemetryLatest]:
    stmt = select(VehicleTelemetryLatest).where(VehicleTelemetryLatest.vin == vin)
    return list((await db.execute(stmt)).scalars().all())


async def _sessions(db: AsyncSession, device_id: str) -> list[DriveSession]:
    stmt = select(DriveSession).where(DriveSession.device_id == device_id)
    return list((await db.execute(stmt)).scalars().all())


async def _dead_wican(make_livelink_vehicle, suffix: str) -> tuple[str, LiveLinkDevice]:
    """A WiCAN whose LWT already landed: offline, last heard from long ago."""
    return await make_livelink_vehicle(
        "retw",
        suffix,
        device_status="offline",
        ecu_status="offline",
        last_seen=OLD,
        battery_voltage=12.0,
    )


class TestWican:
    async def test_a_retained_can_rx_changes_nothing(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """Two moving frames would open a session if they were live."""
        vin, device = await _dead_wican(make_livelink_vehicle, "1")
        await db_session.commit()
        assert device_is_online(device, TIMEOUT_MINUTES, utc_now()) is False

        frame = json.dumps({"SPEED": 52, "ENGINE_RPM": 2200}).encode()
        for _ in range(2):
            await ingest(
                WicanModule(), _retained(f"wican/{device.device_id}/can/rx", frame), db_session
            )
        await db_session.flush()
        await db_session.refresh(device)

        assert await _rows(db_session, device.device_id) == []
        assert await _latest(db_session, vin) == []
        assert await _sessions(db_session, device.device_id) == []
        assert device.device_status == "offline"
        assert device.ecu_status == "offline"
        assert device.last_seen == OLD
        assert device_is_online(device, TIMEOUT_MINUTES, utc_now()) is False

    async def test_a_retained_battery_changes_nothing(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        vin, device = await _dead_wican(make_livelink_vehicle, "2")
        await db_session.commit()

        await ingest(
            WicanModule(),
            _retained(f"wican/{device.device_id}/battery", b'{"battery_voltage": 14.5}'),
            db_session,
        )
        await db_session.flush()
        await db_session.refresh(device)

        assert await _rows(db_session, device.device_id) == []
        assert await _latest(db_session, vin) == []
        assert device.battery_voltage == 12.0
        assert device.device_status == "offline"
        assert device.last_seen == OLD
        assert device_is_online(device, TIMEOUT_MINUTES, utc_now()) is False

    async def test_a_retained_can_status_from_an_unknown_id_discovers_nothing(
        self, db_session: AsyncSession
    ):
        ghost = "retghost0001"
        await db_session.execute(delete(LiveLinkDevice).where(LiveLinkDevice.device_id == ghost))
        await db_session.commit()

        await ingest(
            WicanModule(),
            _retained(f"wican/{ghost}/can/status", b'{"status": "online"}'),
            db_session,
        )
        await db_session.flush()

        found = await db_session.execute(
            select(LiveLinkDevice).where(LiveLinkDevice.device_id == ghost)
        )
        assert found.scalar_one_or_none() is None

    async def test_a_retained_can_status_offline_is_not_a_status_topic(
        self, db_session: AsyncSession, make_livelink_vehicle
    ):
        """WiCAN's status flag is synthesized, never from the wire, so even its
        retained `offline` is dropped: no grace period, no status change."""
        vin, device = await make_livelink_vehicle(
            "retw", "3", device_status="online", ecu_status="online", last_seen=OLD
        )
        await db_session.commit()

        await ingest(
            WicanModule(),
            _retained(f"wican/{device.device_id}/can/status", b'{"status": "offline"}'),
            db_session,
        )
        await db_session.flush()
        await db_session.refresh(device)

        assert device.ecu_status == "online"
        assert device.pending_offline_at is None
        assert device.last_seen == OLD


GEN_T = "retained/test/tank1/level_percent"
GEN_S = "retained/test/status"


@pytest_asyncio.fixture
async def generic(db_session: AsyncSession, make_livelink_vehicle, request):
    """A linked generic_mqtt sensor with a telemetry topic and a status topic.

    The suffix comes from the test name: the suite shares one database, so a
    fixed one collides on the UNIQUE indexes at the second test.
    """
    suffix = f"{abs(hash(request.node.name)) % 10**6:06d}"
    vin, device = await make_livelink_vehicle(
        "retg", suffix, kind="generic_mqtt", device_status="unknown", last_seen=OLD
    )
    await db_session.execute(
        delete(LiveLinkTopicMap).where(LiveLinkTopicMap.topic.in_([GEN_T, GEN_S]))
    )
    db_session.add(
        LiveLinkTopicMap(
            device_id=device.device_id, topic=GEN_T, param_key="RETAINED_T1_LEVEL_PCT", unit="%"
        )
    )
    db_session.add(
        LiveLinkTopicMap(device_id=device.device_id, topic=GEN_S, role="status", param_key=None)
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


class TestGenericMqtt:
    async def test_a_retained_reading_changes_nothing(self, db_session: AsyncSession, generic):
        vin, device, module = generic
        assert device_is_online(device, TIMEOUT_MINUTES, utc_now()) is False

        await ingest(module, _retained(GEN_T, b"71"), db_session)
        await db_session.flush()
        await db_session.refresh(device)

        assert await _rows(db_session, device.device_id) == []
        assert await _latest(db_session, vin) == []
        assert device.device_status == "unknown"
        assert device.last_seen == OLD
        assert device_is_online(device, TIMEOUT_MINUTES, utc_now()) is False

    async def test_a_retained_lwt_offline_still_lands(self, db_session: AsyncSession, generic):
        """Regression guard: the LWT is the one retained message worth applying.

        Main applies every message, this one included, so it passes there by
        design; it pins that the retained-drop rule kept this half.
        """
        vin, device, module = generic
        device.device_status = "online"
        await db_session.commit()

        await ingest(module, _retained(GEN_S, b"offline"), db_session)
        await db_session.flush()
        await db_session.refresh(device)

        assert device.device_status == "offline"

    async def test_a_retained_lwt_offline_does_not_bump_last_seen(
        self, db_session: AsyncSession, generic
    ):
        """A replayed LWT is not the device talking, so last_seen stays put."""
        vin, device, module = generic
        device.device_status = "online"
        await db_session.commit()

        await ingest(module, _retained(GEN_S, b"offline"), db_session)
        await db_session.flush()
        await db_session.refresh(device)

        assert device.device_status == "offline"
        assert device.last_seen == OLD

    async def test_a_retained_online_leaves_an_offline_device_offline(
        self, db_session: AsyncSession, generic
    ):
        """A gateway that died without an LWT leaves `online` retained."""
        vin, device, module = generic
        device.device_status = "offline"
        await db_session.commit()

        await ingest(module, _retained(GEN_S, b"online"), db_session)
        await db_session.flush()
        await db_session.refresh(device)

        assert device.device_status == "offline"
        assert device.last_seen == OLD

    async def test_a_retained_lwt_offline_skips_a_disabled_device(
        self, db_session: AsyncSession, generic
    ):
        """Regression guard: a disabled device freezes at its last status.

        Main returns before any status update for a disabled device; the
        retained-offline path looks the device up on its own and must too.
        """
        vin, device, module = generic
        device.device_status = "online"
        device.enabled = False
        await db_session.commit()

        await ingest(module, _retained(GEN_S, b"offline"), db_session)
        await db_session.flush()
        await db_session.refresh(device)

        assert device.device_status == "online"

    async def test_a_live_online_still_marks_it_online(self, db_session: AsyncSession, generic):
        """Regression guard, the positive control: without it every test above
        passes against a pipeline that stopped applying status at all."""
        vin, device, module = generic
        device.device_status = "offline"
        await db_session.commit()

        await ingest(module, MqttEnvelope(GEN_S, b"online"), db_session)
        await db_session.flush()
        await db_session.refresh(device)

        assert device.device_status == "online"
        assert device.last_seen is not None and device.last_seen > OLD

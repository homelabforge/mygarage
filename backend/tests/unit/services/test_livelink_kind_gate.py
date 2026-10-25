"""A device is ingested only by its own kind's module (FB-1, carry 8).

The pipeline applies the MODULE's capabilities to whatever device
`resolve_device` hands back, and the default lookup was by id with no kind
check. So a WiCAN batch naming a generic sensor's id, or a Torque phone's,
ran that device through the WiCAN pipeline: ECU status, a drive session in
contact mode, odometer sync and DTCs. A Torque token sent as Bearer to the
WiCAN ingest named the phone too, through `get_device_id_by_token`.

Contact mode in each test, so a session would open if the ECU signal got
through to the session service.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_topic_map import LiveLinkTopicMap
from app.models.vehicle_telemetry import VehicleTelemetry
from app.services.livelink_ingest import ingest
from app.services.livelink_service import LiveLinkService
from app.services.livelink_sources.base import MqttEnvelope
from app.services.livelink_sources.generic_mqtt import GenericMqttModule
from app.services.livelink_sources.wican import WicanModule
from app.services.settings_service import SettingsService
from app.services.torque_service import TorqueService
from app.utils.datetime_utils import utc_now

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("livelink_enabled", "contact_mode")]

_SEQ = itertools.count()


@pytest_asyncio.fixture
async def contact_mode(db_session: AsyncSession, keep_rows) -> None:
    await keep_rows("livelink_session_boundary_mode")
    await SettingsService.set(db_session, "livelink_session_boundary_mode", "contact")
    await db_session.commit()


async def _sensor(db: AsyncSession, make_livelink_vehicle) -> tuple[str, str]:
    """A linked generic sensor, quiet and unknown, as a preset leaves one."""
    vin, device = await make_livelink_vehicle(
        "kgsen",
        str(next(_SEQ)),
        kind="generic_mqtt",
        device_status="unknown",
        ecu_status="unknown",
    )
    device_id = device.device_id
    await db.commit()
    return vin, device_id


async def _device(db: AsyncSession, device_id: str) -> LiveLinkDevice:
    db.expire_all()
    return (
        await db.execute(select(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id))
    ).scalar_one()


async def _rows(db: AsyncSession, device_id: str) -> list[VehicleTelemetry]:
    stmt = select(VehicleTelemetry).where(VehicleTelemetry.device_id == device_id)
    return list((await db.execute(stmt)).scalars().all())


async def _sessions(db: AsyncSession, device_id: str) -> list[DriveSession]:
    stmt = select(DriveSession).where(DriveSession.device_id == device_id)
    return list((await db.execute(stmt)).scalars().all())


async def _post_any_token(client: AsyncClient, body: dict[str, Any]) -> Response:
    """The holder of the global token, which passes for any device id."""
    with patch("app.routes.livelink.validate_livelink_token", new_callable=AsyncMock) as ok:
        ok.return_value = True
        return await client.post(
            "/api/v1/livelink/ingest", json=body, headers={"Authorization": "Bearer t"}
        )


async def test_an_https_status_post_naming_a_sensor_leaves_it_alone(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle
):
    """FB-1's scenario: the sensor got ecu_status online, a drive on a parked
    trailer and the readings under WiCAN's storage policy."""
    _vin, sensor_id = await _sensor(db_session, make_livelink_vehicle)

    response = await _post_any_token(
        client,
        {
            "status": {"device_id": sensor_id, "ecu_status": "online", "hw_version": "WiCAN-PRO"},
            "autopid_data": {"SPEED": 40},
        },
    )

    assert response.json()["status"] == "rejected"
    after = await _device(db_session, sensor_id)
    assert (after.ecu_status, after.device_status, after.hw_version) == (
        "unknown",
        "unknown",
        None,
    )
    assert await _rows(db_session, sensor_id) == []
    assert await _sessions(db_session, sensor_id) == []


async def test_a_wican_mqtt_topic_naming_a_sensor_leaves_it_alone(
    db_session: AsyncSession, make_livelink_vehicle
):
    """The same through `wican/<id>/can/rx`."""
    _vin, sensor_id = await _sensor(db_session, make_livelink_vehicle)

    outcome = await ingest(
        WicanModule(),
        MqttEnvelope(f"wican/{sensor_id}/can/rx", json.dumps({"SPEED": 40}).encode()),
        db_session,
    )
    await db_session.commit()

    assert outcome.device is None
    after = await _device(db_session, sensor_id)
    assert (after.ecu_status, after.device_status) == ("unknown", "unknown")
    assert await _rows(db_session, sensor_id) == []
    assert await _sessions(db_session, sensor_id) == []


@pytest_asyncio.fixture
async def phone(db_session: AsyncSession, make_livelink_vehicle) -> tuple[str, str]:
    """A linked Torque phone and its raw path token."""
    vin, _wican = await make_livelink_vehicle("kgtq", str(next(_SEQ)))
    device, token = await TorqueService(db_session).create_source(vin)
    device_id = device.device_id
    await db_session.commit()
    return device_id, token


async def test_a_torque_token_does_not_name_a_device_for_the_wican_ingest(
    db_session: AsyncSession, phone: tuple[str, str]
):
    """Carry 8: step 1 of the lookup matched any kind's per-device token."""
    device_id, token = phone

    found = await LiveLinkService(db_session).get_device_id_by_token(f"Bearer {token}")

    assert found != device_id


async def test_a_torque_token_sent_to_the_wican_ingest_stores_nothing(
    db_session: AsyncSession, client: AsyncClient, phone: tuple[str, str]
):
    """The real token check: the phone's own token got its id through, and the
    WiCAN pipeline marked its ECU on and stored the reading."""
    device_id, token = phone

    response = await client.post(
        "/api/v1/livelink/ingest",
        json={"autopid_data": {"SPEED": 40}},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401 or response.json()["status"] == "rejected"
    assert (await _device(db_session, device_id)).ecu_status == "unknown"
    assert await _rows(db_session, device_id) == []


async def test_a_status_post_naming_a_torque_phone_with_its_token_stores_nothing(
    db_session: AsyncSession, client: AsyncClient, phone: tuple[str, str]
):
    """The status block names the device, and the phone's token is valid for
    it, so only the kind check stands between the phone and WiCAN's pipeline."""
    device_id, token = phone

    response = await client.post(
        "/api/v1/livelink/ingest",
        json={"status": {"device_id": device_id, "ecu_status": "online"}, "autopid_data": {}},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.json()["status"] == "rejected"
    after = await _device(db_session, device_id)
    assert (after.ecu_status, after.device_status) == ("unknown", "unknown")
    assert await _sessions(db_session, device_id) == []


GEN_T = "kindgate/test/level"
GEN_S = "kindgate/test/status"


@pytest_asyncio.fixture
async def mapped_to_a_wican(
    db_session: AsyncSession, make_livelink_vehicle
) -> AsyncGenerator[tuple[str, GenericMqttModule]]:
    """Topic maps that name a WiCAN. The admin API doesn't check the kind."""
    _vin, wican = await make_livelink_vehicle(
        "kgwic", str(next(_SEQ)), device_status="online", ecu_status="online"
    )
    device_id = wican.device_id
    await db_session.execute(
        delete(LiveLinkTopicMap).where(LiveLinkTopicMap.topic.in_([GEN_T, GEN_S]))
    )
    db_session.add(
        LiveLinkTopicMap(device_id=device_id, topic=GEN_T, param_key="KINDGATE_LEVEL", unit="%")
    )
    db_session.add(LiveLinkTopicMap(device_id=device_id, topic=GEN_S, role="status"))
    await db_session.commit()
    module = GenericMqttModule()
    await module.refresh(db_session)

    yield device_id, module

    await db_session.rollback()
    await db_session.execute(
        delete(LiveLinkTopicMap).where(LiveLinkTopicMap.device_id == device_id)
    )
    await db_session.commit()


async def test_a_generic_topic_mapped_to_a_wican_stores_nothing(
    db_session: AsyncSession, mapped_to_a_wican: tuple[str, GenericMqttModule]
):
    device_id, module = mapped_to_a_wican

    await ingest(module, MqttEnvelope(GEN_T, b"42"), db_session)
    await db_session.commit()

    assert await _rows(db_session, device_id) == []


async def test_a_retained_lwt_mapped_to_a_wican_leaves_it_alone(
    db_session: AsyncSession, mapped_to_a_wican: tuple[str, GenericMqttModule]
):
    """The retained-offline path looks the device up on its own."""
    device_id, module = mapped_to_a_wican
    seen = (await _device(db_session, device_id)).last_seen

    await ingest(module, MqttEnvelope(GEN_S, b"offline", retain=True), db_session)
    await db_session.commit()

    after = await _device(db_session, device_id)
    assert (after.device_status, after.last_seen) == ("online", seen)


async def test_a_wicans_own_status_post_still_lands(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle
):
    """Regression guard, the positive control: without it the tests above pass
    against a pipeline that refuses everyone."""
    _vin, wican = await make_livelink_vehicle("kgown", str(next(_SEQ)), ecu_status="offline")
    device_id = wican.device_id
    await db_session.commit()
    before = utc_now()

    response = await _post_any_token(
        client,
        {"status": {"device_id": device_id, "ecu_status": "online"}, "autopid_data": {}},
    )

    assert response.json()["status"] == "accepted"
    after = await _device(db_session, device_id)
    assert after.ecu_status == "online"
    assert after.last_seen is not None and after.last_seen >= before.replace(tzinfo=None)
    assert len(await _sessions(db_session, device_id)) == 1

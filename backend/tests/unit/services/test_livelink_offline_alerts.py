"""Offline alerts for generic_mqtt sensors with no status topic (D5a, A-13).

The offline sweep only looks at devices whose `device_status` is 'online', so
a sensor that never sent a status sat at 'unknown' and never alerted. A live
reading now marks a generic device online (WiCAN's `can/rx` already did), so
the sweep's one-alert-per-outage rule covers every sensor. The tests run the
real scheduled job against the test session, with the dispatcher's `dispatch`
recording what would have gone out.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_topic_map import LiveLinkTopicMap
from app.models.settings import Setting
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_telemetry import VehicleTelemetryLatest
from app.services.livelink_ingest import ingest
from app.services.livelink_integrations import device_is_online
from app.services.livelink_sources.base import HttpEnvelope, MqttEnvelope
from app.services.livelink_sources.generic_mqtt import GenericMqttModule
from app.services.livelink_sources.torque import TorqueModule
from app.services.notifications.dispatcher import NotificationDispatcher
from app.services.torque_service import TorqueService
from app.utils.datetime_utils import utc_now

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("livelink_enabled", "notify_offline")]

#: Long past any offline timeout.
OLD = datetime(2026, 9, 1, 8, 0, 0)
TIMEOUT_MINUTES = 10

VEHICLE_HINT = "Check vehicle battery and WiFi connectivity"
DEVICE_HINT = "Check the device and its network connection"


@pytest_asyncio.fixture
async def notify_offline(db_session: AsyncSession) -> AsyncIterator[None]:
    """The offline switch on for one test, put back after (shared database)."""
    key = "livelink_notify_device_offline"
    existing = await db_session.get(Setting, key)
    previous = existing.value if existing is not None else None
    if existing is not None:
        existing.value = "true"
    else:
        db_session.add(Setting(key=key, value="true"))
    await db_session.commit()

    yield

    await db_session.rollback()
    row = await db_session.get(Setting, key)
    if previous is None:
        if row is not None:
            await db_session.delete(row)
    elif row is not None:
        row.value = previous
    await db_session.commit()


@pytest.fixture
def suffix(request: pytest.FixtureRequest) -> str:
    """Per-test identifiers: the suite shares one database."""
    return f"{abs(hash(request.node.name)) % 10**6:06d}"


async def _sweep(db: AsyncSession, caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    """Run the scheduled offline sweep once and return what it dispatched.

    The job swallows its own exceptions, so an error it logged fails the test
    here instead of reading as "no alert".
    """
    from app.tasks import livelink_tasks

    sent: list[dict[str, Any]] = []

    async def _dispatch(
        self: NotificationDispatcher, event_type: str, title: str, message: str, **_: Any
    ) -> dict[str, bool]:
        sent.append({"event_type": event_type, "title": title, "message": message})
        return {}

    with (
        patch.object(livelink_tasks, "AsyncSessionLocal", lambda: contextlib.nullcontext(db)),
        patch.object(NotificationDispatcher, "dispatch", _dispatch),
        caplog.at_level(logging.ERROR, logger="app.tasks.livelink_tasks"),
    ):
        caplog.clear()
        await livelink_tasks.check_device_offline_status()
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors == [], errors
    return sent


def _for(sent: list[dict[str, Any]], device_id: str) -> list[dict[str, Any]]:
    """The alerts about one device (the sweep sees the whole shared database)."""
    return [n for n in sent if f"Device {device_id} " in n["message"]]


async def _device(db: AsyncSession, device_id: str) -> LiveLinkDevice:
    db.expire_all()
    stmt = select(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id)
    return (await db.execute(stmt)).scalar_one()


async def _go_quiet(db: AsyncSession, device_id: str) -> None:
    """The device's last word was long ago."""
    await db.execute(
        update(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id).values(last_seen=OLD)
    )
    await db.commit()


async def _map(db: AsyncSession, device_id: str, *rows: LiveLinkTopicMap) -> GenericMqttModule:
    topics = {r.topic for r in rows}
    await db.execute(delete(LiveLinkTopicMap).where(LiveLinkTopicMap.topic.in_(topics)))
    for row in rows:
        row.device_id = device_id
        db.add(row)
    await db.commit()
    module = GenericMqttModule()
    await module.refresh(db)
    return module


@pytest_asyncio.fixture
async def cleanup_maps(db_session: AsyncSession) -> AsyncIterator[list[str]]:
    """Device ids whose topic maps go when the test ends."""
    ids: list[str] = []
    yield ids
    await db_session.rollback()
    if ids:
        await db_session.execute(
            delete(LiveLinkTopicMap).where(LiveLinkTopicMap.device_id.in_(ids))
        )
        await db_session.commit()


async def _mopeka(
    db: AsyncSession, make_livelink_vehicle, cleanup_maps: list[str], suffix: str, **kwargs: Any
) -> tuple[str, LiveLinkDevice, GenericMqttModule, str]:
    """A Mopeka-shaped sensor: preset, one level topic, no status topic."""
    kwargs.setdefault("device_status", "unknown")
    kwargs.setdefault("last_seen", OLD)
    vin, device = await make_livelink_vehicle(
        "offm", suffix, kind="generic_mqtt", preset_key="mopeka", **kwargs
    )
    topic = f"offline/test/{suffix}/tank1/level_percent"
    module = await _map(
        db,
        device.device_id,
        LiveLinkTopicMap(
            device_id=device.device_id, topic=topic, param_key=f"OFFM{suffix}_LEVEL_PCT", unit="%"
        ),
    )
    cleanup_maps.append(device.device_id)
    return vin, device, module, topic


async def _status_sensor(
    db: AsyncSession, make_livelink_vehicle, cleanup_maps: list[str], suffix: str, **kwargs: Any
) -> tuple[LiveLinkDevice, GenericMqttModule, str, str]:
    """A generic sensor with a level topic AND a status (LWT) topic."""
    kwargs.setdefault("last_seen", OLD)
    _vin, device = await make_livelink_vehicle("offs", suffix, kind="generic_mqtt", **kwargs)
    level = f"offline/test/{suffix}/level"
    status = f"offline/test/{suffix}/status"
    module = await _map(
        db,
        device.device_id,
        LiveLinkTopicMap(
            device_id=device.device_id, topic=level, param_key=f"OFFS{suffix}_LEVEL_PCT", unit="%"
        ),
        LiveLinkTopicMap(device_id=device.device_id, topic=status, role="status", param_key=None),
    )
    cleanup_maps.append(device.device_id)
    return device, module, level, status


async def test_a_status_less_sensor_alerts_once_per_outage(
    db_session: AsyncSession, make_livelink_vehicle, cleanup_maps, suffix, caplog
):
    """D5a: one alert per outage, re-armed by the next live reading."""
    _vin, device, module, topic = await _mopeka(
        db_session, make_livelink_vehicle, cleanup_maps, suffix
    )
    device_id = device.device_id

    await ingest(module, MqttEnvelope(topic, b"71"), db_session)
    await db_session.commit()
    assert (await _device(db_session, device_id)).device_status == "online"

    await _go_quiet(db_session, device_id)
    assert len(_for(await _sweep(db_session, caplog), device_id)) == 1
    assert (await _device(db_session, device_id)).device_status == "offline"
    assert _for(await _sweep(db_session, caplog), device_id) == []

    await ingest(module, MqttEnvelope(topic, b"70"), db_session)
    await db_session.commit()
    assert (await _device(db_session, device_id)).device_status == "online"
    await _go_quiet(db_session, device_id)
    assert len(_for(await _sweep(db_session, caplog), device_id)) == 1


async def test_a_missed_birth_comes_back_online_on_its_first_reading(
    db_session: AsyncSession, make_livelink_vehicle, cleanup_maps, suffix
):
    """Fable F2-1: the `online` birth went out retained while MyGarage was down.

    R1 drops it, so without the reading flip the live LWT `offline` stood for
    good, and `device_is_online` never falls back to last_seen for 'offline'.
    """
    device, module, level, status = await _status_sensor(
        db_session, make_livelink_vehicle, cleanup_maps, suffix, device_status="online"
    )
    device_id = device.device_id

    await ingest(module, MqttEnvelope(status, b"offline"), db_session)
    await ingest(module, MqttEnvelope(status, b"online", retain=True), db_session)
    await db_session.commit()
    assert (await _device(db_session, device_id)).device_status == "offline"

    await ingest(module, MqttEnvelope(level, b"55"), db_session)
    await db_session.commit()

    refreshed = await _device(db_session, device_id)
    assert refreshed.device_status == "online"
    assert device_is_online(refreshed, TIMEOUT_MINUTES, utc_now()) is True


async def test_a_status_topic_device_alerts_once(
    db_session: AsyncSession, make_livelink_vehicle, cleanup_maps, suffix, caplog
):
    """Regression guard (Fable F2-2): a status-topic device that goes quiet
    gets exactly one alert, as on main."""
    device, module, _level, status = await _status_sensor(
        db_session, make_livelink_vehicle, cleanup_maps, suffix, device_status="unknown"
    )
    device_id = device.device_id

    await ingest(module, MqttEnvelope(status, b"online"), db_session)
    await db_session.commit()
    await _go_quiet(db_session, device_id)

    first = _for(await _sweep(db_session, caplog), device_id)
    second = _for(await _sweep(db_session, caplog), device_id)
    assert len(first) == 1
    assert second == []


async def test_a_retained_reading_after_offline_leaves_it_offline(
    db_session: AsyncSession, make_livelink_vehicle, cleanup_maps, suffix
):
    """Regression guard: the reading flip is for LIVE readings only.

    T1's `test_a_retained_reading_changes_nothing` (test_livelink_retained.py)
    covers an 'unknown' device; this is the dead-gateway case the flip could
    have revived, which R1's retained drop keeps out.
    """
    device, module, level, _status = await _status_sensor(
        db_session, make_livelink_vehicle, cleanup_maps, suffix, device_status="offline"
    )

    await ingest(module, MqttEnvelope(level, b"40", retain=True), db_session)
    await db_session.commit()

    refreshed = await _device(db_session, device.device_id)
    assert refreshed.device_status == "offline"
    assert refreshed.last_seen == OLD


async def test_a_torque_source_never_alerts(db_session: AsyncSession, suffix, caplog):
    """Regression guard: a phone uploads only while driving, so Torque stays
    'unknown' and never enters the sweep."""
    user = User(
        username=f"offt_user_{suffix}",
        email=f"offt_{suffix}@example.com",
        hashed_password="x",
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.flush()
    vin = f"OFFT{suffix:0>6}"
    db_session.add(Vehicle(vin=vin, user_id=user.id, nickname=f"offt {suffix}", vehicle_type="Car"))
    await db_session.flush()
    device, token = await TorqueService(db_session).create_source(vin)
    await db_session.commit()
    device_id = device.device_id

    await ingest(TorqueModule(), HttpEnvelope(token=token, params={"k0c": "1800"}), db_session)
    await db_session.commit()
    assert (await _device(db_session, device_id)).device_status == "unknown"

    await _go_quiet(db_session, device_id)
    assert _for(await _sweep(db_session, caplog), device_id) == []
    assert (await _device(db_session, device_id)).device_status == "unknown"


async def test_one_message_with_both_roles_stays_offline(
    db_session: AsyncSession, make_livelink_vehicle, cleanup_maps, suffix
):
    """Fable F3-4: one topic can carry the status AND a reading. The reading
    must not overrule the status the same message gave."""
    vin, device = await make_livelink_vehicle(
        "offb", suffix, kind="generic_mqtt", device_status="online", last_seen=OLD
    )
    topic = f"offline/test/{suffix}/combined"
    key = f"OFFB{suffix}_LEVEL_PCT"
    module = await _map(
        db_session,
        device.device_id,
        LiveLinkTopicMap(
            device_id=device.device_id,
            topic=topic,
            role="status",
            param_key=None,
            value_path="available",
        ),
        LiveLinkTopicMap(
            device_id=device.device_id, topic=topic, param_key=key, value_path="level", unit="%"
        ),
    )
    cleanup_maps.append(device.device_id)

    await ingest(module, MqttEnvelope(topic, b'{"available": false, "level": 42}'), db_session)
    await db_session.commit()

    assert (await _device(db_session, device.device_id)).device_status == "offline"
    latest = (
        await db_session.execute(
            select(VehicleTelemetryLatest).where(
                VehicleTelemetryLatest.vin == vin, VehicleTelemetryLatest.param_key == key
            )
        )
    ).scalar_one()
    assert latest.value == 42


async def test_a_sensor_keeps_its_ecu_status(
    db_session: AsyncSession, make_livelink_vehicle, cleanup_maps, suffix, caplog
):
    """A sensor has no ECU, and its batches never reset one, so the sweep
    leaves `ecu_status` alone. A WiCAN's still goes offline with it."""
    _vin, sensor, _m, _t = await _mopeka(
        db_session, make_livelink_vehicle, cleanup_maps, suffix, device_status="online"
    )
    _vin2, wican = await make_livelink_vehicle(
        "offw", suffix, device_status="online", ecu_status="online", last_seen=OLD
    )
    sensor_id, wican_id = sensor.device_id, wican.device_id
    await db_session.commit()

    await _sweep(db_session, caplog)

    refreshed = await _device(db_session, sensor_id)
    assert refreshed.device_status == "offline"
    assert refreshed.ecu_status == "unknown"
    refreshed_wican = await _device(db_session, wican_id)
    assert refreshed_wican.device_status == "offline"
    assert refreshed_wican.ecu_status == "offline"


async def test_the_offline_alert_words_a_sensor_as_a_device(
    db_session: AsyncSession, make_livelink_vehicle, cleanup_maps, suffix, caplog
):
    """Fable F3-5: "check vehicle battery" is wrong for a propane sensor. A
    WiCAN keeps the vehicle wording."""
    _vin, sensor, _m, _t = await _mopeka(
        db_session, make_livelink_vehicle, cleanup_maps, suffix, device_status="online"
    )
    _vin2, wican = await make_livelink_vehicle(
        "offv", suffix, device_status="online", ecu_status="online", last_seen=OLD
    )
    sensor_id, wican_id = sensor.device_id, wican.device_id
    await db_session.commit()

    sent = await _sweep(db_session, caplog)

    (sensor_alert,) = _for(sent, sensor_id)
    assert DEVICE_HINT in sensor_alert["message"]
    assert "vehicle battery" not in sensor_alert["message"]
    (wican_alert,) = _for(sent, wican_id)
    assert VEHICLE_HINT in wican_alert["message"]


async def test_the_offline_alert_names_the_vehicle_by_its_nickname(
    db_session: AsyncSession, make_livelink_vehicle, suffix, caplog
):
    """A vehicle with no year, make or model was named "None None None"; the
    other notifications already prefer the nickname."""
    _vin, wican = await make_livelink_vehicle(
        "offn", suffix, device_status="online", ecu_status="online", last_seen=OLD
    )
    wican_id = wican.device_id
    await db_session.commit()

    (alert,) = _for(await _sweep(db_session, caplog), wican_id)

    assert alert["title"] == f"LiveLink Device Offline for offn {suffix}"
    assert "None" not in alert["message"]


async def test_an_unregistered_kind_goes_offline_without_aborting_the_sweep(
    db_session: AsyncSession, make_livelink_vehicle, cleanup_maps, suffix, caplog
):
    """Fable F5-3: a kind with no module (one removed in a later release) has
    no capabilities. The sweep's one `try` wraps every device, so a raise
    there would drop the whole sweep, the sensor's alert included."""
    _vin, orphan = await make_livelink_vehicle(
        "offu", suffix, kind="retired_source", device_status="online", last_seen=OLD
    )
    _vin2, sensor, _m, _t = await _mopeka(
        db_session, make_livelink_vehicle, cleanup_maps, suffix, device_status="online"
    )
    orphan_id, sensor_id = orphan.device_id, sensor.device_id
    await db_session.commit()

    sent = await _sweep(db_session, caplog)

    for device_id in (orphan_id, sensor_id):
        assert (await _device(db_session, device_id)).device_status == "offline"
        (alert,) = _for(sent, device_id)
        assert DEVICE_HINT in alert["message"]
    assert (await _device(db_session, orphan_id)).ecu_status == "unknown"

"""WiCAN HTTPS on the ingest pipeline (G5b-14, A-4, D4a, N-2, R4, R5, R12).

Driven through the real route. The route used to call `store_telemetry`
itself, so a disabled device kept storing, a telemetry-only POST never cleared
a pending offline or marked the ECU on, and the `config` a WiCAN sends once per
boot lived for one request. These pin the pipeline's version of each.

The R12 model is imported inside the tests that need it, so before T3 only
those fail on the import and the rest fail on behaviour.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import get_db
from app.main import app
from app.models.drive_session import DriveSession
from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_parameter import LiveLinkParameter
from app.models.livelink_topic_map import LiveLinkTopicMap
from app.models.vehicle_dtc import VehicleDTC
from app.models.vehicle_telemetry import VehicleTelemetry
from app.services import declared_units
from app.services.livelink_ingest import ingest
from app.services.livelink_service import LiveLinkService
from app.services.livelink_sources.base import MqttEnvelope
from app.services.livelink_sources.generic_mqtt import GenericMqttModule
from app.services.livelink_sources.wican import WicanModule
from app.services.settings_service import SettingsService
from app.utils.datetime_utils import utc_now

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("livelink_enabled")]

#: 50 mph in km/h, unrounded: the write path keeps full precision.
KMH_50_MPH = 50 * 1.609344

_SEQ = itertools.count()


def _uid(prefix: str) -> str:
    """A device id no other test (or rerun) in this file uses."""
    return f"{prefix}{next(_SEQ):04d}{utc_now().strftime('%H%M%S%f')[-8:]}"[:20]


async def _post(client: AsyncClient, body: dict[str, Any], token: str = "t") -> Response:
    with patch("app.routes.livelink.validate_livelink_token", new_callable=AsyncMock) as ok:
        ok.return_value = True
        return await client.post(
            "/api/v1/livelink/ingest",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )


def _boot(device_id: str, config: dict[str, Any], **autopid: float) -> dict[str, Any]:
    """A cold-boot POST: status block plus the device's whole config."""
    return {
        "autopid_data": dict(autopid),
        "config": config,
        "status": {"device_id": device_id, "ecu_status": "online"},
    }


SPEED_MPH = {"SPEED": {"class": "speed", "unit": "mph"}}


async def _values(db: AsyncSession, device_id: str, key: str) -> list[float]:
    rows = await db.execute(
        select(VehicleTelemetry.value)
        .where(VehicleTelemetry.device_id == device_id, VehicleTelemetry.param_key == key)
        .order_by(VehicleTelemetry.timestamp)
    )
    return list(rows.scalars().all())


async def _units(db: AsyncSession, device_id: str) -> dict[str, tuple[str | None, str | None, str]]:
    from app.models.livelink_device_unit import LiveLinkDeviceUnit

    rows = await db.execute(
        select(
            LiveLinkDeviceUnit.param_key,
            LiveLinkDeviceUnit.unit,
            LiveLinkDeviceUnit.param_class,
            LiveLinkDeviceUnit.source,
        ).where(LiveLinkDeviceUnit.device_id == device_id)
    )
    return {key: (unit, cls, source) for key, unit, cls, source in rows.all()}


async def _device(db: AsyncSession, device_id: str) -> LiveLinkDevice:
    db.expire_all()
    found = (
        await db.execute(select(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id))
    ).scalar_one()
    return found


async def _linked(
    db: AsyncSession, make_livelink_vehicle, prefix: str, **device_fields: Any
) -> tuple[str, LiveLinkDevice, str]:
    """A linked WiCAN with its own token, so a telemetry-only POST finds it.

    A global-token POST resolves only when exactly one WiCAN is enabled, and
    the suite's database holds many.
    """
    n = next(_SEQ)
    token = f"t3-{prefix}-{n}-{utc_now().timestamp()}"
    vin, device = await make_livelink_vehicle(
        prefix, str(n), device_token_hash=LiveLinkService.hash_token(token)
    )
    for field, value in device_fields.items():
        setattr(device, field, value)
    await db.commit()
    return vin, device, token


@pytest_asyncio.fixture
async def fresh_params(db_session: AsyncSession) -> AsyncGenerator[Callable[..., Awaitable[None]]]:
    """Drop global parameter rows for a test and put them back afterwards.

    Parameter rows are fleet-wide and the suite shares one database, so a test
    that asserts what a row registers as has to start without it.
    """
    saved: dict[str, dict[str, Any] | None] = {}
    attrs = [a.key for a in LiveLinkParameter.__mapper__.column_attrs if a.key != "id"]

    async def take(*keys: str) -> None:
        loaded: list[LiveLinkParameter] = []
        for key in keys:
            row = (
                await db_session.execute(
                    select(LiveLinkParameter).where(LiveLinkParameter.param_key == key)
                )
            ).scalar_one_or_none()
            saved.setdefault(key, None if row is None else {a: getattr(row, a) for a in attrs})
            if row is not None:
                loaded.append(row)
        await db_session.execute(
            delete(LiveLinkParameter).where(LiveLinkParameter.param_key.in_(list(keys)))
        )
        # The Core delete leaves the old objects in the identity map, and SQLite
        # can hand a new row the same id: SQLAlchemy then warns it replaced one.
        for row in loaded:
            db_session.expunge(row)
        await db_session.commit()

    yield take

    await db_session.rollback()
    await db_session.execute(
        delete(LiveLinkParameter).where(LiveLinkParameter.param_key.in_(list(saved)))
    )
    db_session.expunge_all()  # same reason as in `take`
    for snapshot in saved.values():
        if snapshot is not None:
            db_session.add(LiveLinkParameter(**snapshot))
    await db_session.commit()


async def _param(db: AsyncSession, key: str) -> LiveLinkParameter:
    db.expire_all()
    return (
        await db.execute(select(LiveLinkParameter).where(LiveLinkParameter.param_key == key))
    ).scalar_one()


# --- A-4: a disabled device -----------------------------------------------------


async def test_a_disabled_device_records_units_and_versions_and_nothing_else(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle
):
    """Fable F4-6: every field a live status would move stays put.

    Declarations and versions are device metadata, so they still land: a
    device disabled for a day that reboots would otherwise lose its units
    until its next boot.
    """
    seen = utc_now() - timedelta(hours=2)
    vin, device, _token = await _linked(
        db_session,
        make_livelink_vehicle,
        "t3dis",
        device_status="offline",
        ecu_status="offline",
        last_seen=seen,
        rssi=-70,
        battery_voltage=12.1,
        pending_offline_at=seen,
        sta_ip="10.0.0.1",
        fw_version="1.0",
    )
    session = DriveSession(vin=vin, device_id=device.device_id, started_at=seen)
    db_session.add(session)
    await db_session.flush()
    device.current_session_id = session.id
    device.enabled = False
    device_id, session_id = device.device_id, session.id
    await db_session.commit()

    response = await _post(
        client,
        {
            "autopid_data": {"SPEED": 40, "DIAGNOSTIC_TROUBLE_CODES": "P0301"},
            "config": {"SPEED": {"class": "speed", "unit": "km/h"}},
            "status": {
                "device_id": device_id,
                "ecu_status": "online",
                "hw_version": "WiCAN-OBD-PRO",
                "fw_version": "4.50",
                "git_version": "v4.50p",
                "sta_ip": "10.0.0.9",
                "rssi": -40,
                "battery_voltage": 13.9,
            },
        },
    )

    assert response.status_code == 202
    assert response.json()["status"] == "disabled"
    assert await _values(db_session, device_id, "SPEED") == []
    dtcs = await db_session.execute(select(VehicleDTC).where(VehicleDTC.vin == vin))
    assert dtcs.scalars().all() == []
    sessions = (
        (await db_session.execute(select(DriveSession).where(DriveSession.device_id == device_id)))
        .scalars()
        .all()
    )
    assert [(s.id, s.ended_at) for s in sessions] == [(session_id, None)]

    after = await _device(db_session, device_id)
    assert after.device_status == "offline"
    assert after.ecu_status == "offline"
    assert after.last_seen == seen
    assert after.rssi == -70
    assert after.battery_voltage == 12.1
    assert after.pending_offline_at == seen
    assert after.current_session_id == session_id
    # The metadata does refresh.
    assert (after.hw_version, after.fw_version, after.git_version) == (
        "WiCAN-OBD-PRO",
        "4.50",
        "v4.50p",
    )
    assert after.sta_ip == "10.0.0.9"
    assert await _units(db_session, device_id) == {"SPEED": ("km/h", "speed", "wire")}


# --- R12: the boot config outlives its request ----------------------------------


async def test_an_empty_config_keeps_the_boot_units_and_a_new_boot_replaces_them(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, fresh_params
):
    """Fable F4-1: the schema defaults `config` to `{}`, so a status payload
    alone must never wipe what the boot declared. A boot `config` is the whole
    profile: keys it drops go, `legacy` rows stay."""
    from app.models.livelink_device_unit import LiveLinkDeviceUnit

    await fresh_params("SPEED")
    _vin, device, token = await _linked(db_session, make_livelink_vehicle, "t3prof")
    device_id = device.device_id

    await _post(client, _boot(device_id, {**SPEED_MPH, "COOLANT_TEMP": {"unit": "°C"}}))
    # A status payload with the default empty config: not a boot declaration.
    await _post(client, _boot(device_id, {}))
    assert (await _units(db_session, device_id))["SPEED"] == ("mph", "speed", "wire")

    await _post(client, {"autopid_data": {"SPEED": 50}}, token)
    assert await _values(db_session, device_id, "SPEED") == [pytest.approx(KMH_50_MPH)]

    db_session.add(
        LiveLinkDeviceUnit(device_id=device_id, param_key="ODOMETER", unit="mi", source="legacy")
    )
    await db_session.commit()
    await _post(client, _boot(device_id, {"COOLANT_TEMP": {"unit": "°C"}}))

    assert await _units(db_session, device_id) == {
        "COOLANT_TEMP": ("°C", "temperature", "wire"),
        "ODOMETER": ("mi", None, "legacy"),
    }


async def test_units_declared_at_boot_survive_a_restart(
    db_session: AsyncSession,
    client: AsyncClient,
    make_livelink_vehicle,
    fresh_params,
    test_sessionmaker: async_sessionmaker[AsyncSession],
):
    """Codex R1-H2: WiCAN declares once per boot and MyGarage restarts mid-drive.

    Nothing in process memory may carry the unit: the in-memory map is cleared
    and the telemetry-only POST runs in a brand-new session.
    """
    await fresh_params("SPEED")
    _vin, device, token = await _linked(db_session, make_livelink_vehicle, "t3rst")
    device_id = device.device_id
    await _post(client, _boot(device_id, SPEED_MPH))

    declared_units._BY_DEVICE.clear()
    previous = app.dependency_overrides[get_db]
    async with test_sessionmaker() as fresh:

        async def _fresh_db() -> AsyncGenerator[AsyncSession]:
            yield fresh

        app.dependency_overrides[get_db] = _fresh_db
        try:
            response = await _post(client, {"autopid_data": {"SPEED": 50}}, token)
        finally:
            app.dependency_overrides[get_db] = previous

    assert "processing_error" not in response.json()
    assert await _values(db_session, device_id, "SPEED") == [pytest.approx(KMH_50_MPH)]


TOPIC_MPH = "t3units/test/speed"


async def test_a_topic_map_unit_of_mph_converts_the_same_way(
    db_session: AsyncSession, make_livelink_vehicle, fresh_params
):
    """R4 runs on every unit a reading resolves to, a topic map's included."""
    key = "T3_TOPIC_SPEED"
    await fresh_params(key)
    _vin, device = await make_livelink_vehicle("t3topic", "1", kind="generic_mqtt")
    await db_session.execute(delete(LiveLinkTopicMap).where(LiveLinkTopicMap.topic == TOPIC_MPH))
    db_session.add(
        LiveLinkTopicMap(device_id=device.device_id, topic=TOPIC_MPH, param_key=key, unit="mph")
    )
    await db_session.commit()
    module = GenericMqttModule()
    await module.refresh(db_session)
    device_id = device.device_id

    try:
        await ingest(module, MqttEnvelope(TOPIC_MPH, b"50"), db_session)
        await db_session.commit()

        assert await _values(db_session, device_id, key) == [pytest.approx(KMH_50_MPH)]
        assert (await _param(db_session, key)).unit == "km/h"
    finally:
        await db_session.rollback()
        await db_session.execute(
            delete(LiveLinkTopicMap).where(LiveLinkTopicMap.device_id == device_id)
        )
        await db_session.commit()


async def test_a_device_declares_its_units_before_it_is_linked(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, fresh_params
):
    """Fable F1-1: the boot POST is the only one carrying `config`, and a new
    device is still unlinked when it arrives, so the units must be recorded
    before the link check."""
    await fresh_params("SPEED")
    vin, _other = await make_livelink_vehicle("t3onb", "1")
    await db_session.commit()
    device_id = _uid("t3onb")

    await _post(client, _boot(device_id, SPEED_MPH))

    token = f"t3-onboard-{device_id}"
    device = await _device(db_session, device_id)
    assert device.vin is None
    device.vin = vin
    device.device_token_hash = LiveLinkService.hash_token(token)
    await db_session.commit()

    await _post(client, {"autopid_data": {"SPEED": 50}}, token)

    assert await _values(db_session, device_id, "SPEED") == [pytest.approx(KMH_50_MPH)]


async def test_a_device_disabled_at_boot_keeps_its_units_once_enabled(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, fresh_params
):
    """Fable F2-5: the units land before the `enabled` check too."""
    await fresh_params("SPEED")
    _vin, device, token = await _linked(db_session, make_livelink_vehicle, "t3off")
    device.enabled = False
    device_id = device.device_id
    await db_session.commit()

    await _post(client, _boot(device_id, SPEED_MPH))

    device = await _device(db_session, device_id)
    device.enabled = True
    await db_session.commit()
    await _post(client, {"autopid_data": {"SPEED": 50}}, token)

    assert await _values(db_session, device_id, "SPEED") == [pytest.approx(KMH_50_MPH)]


# --- R4: mph is stored as km/h ---------------------------------------------------


async def test_a_declared_mph_speed_is_stored_and_registered_as_kmh(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, fresh_params
):
    await fresh_params("SPEED")
    _vin, device, _token = await _linked(db_session, make_livelink_vehicle, "t3mph")
    device_id = device.device_id

    await _post(client, _boot(device_id, SPEED_MPH, SPEED=50))

    assert await _values(db_session, device_id, "SPEED") == [pytest.approx(KMH_50_MPH)]
    assert (await _param(db_session, "SPEED")).unit == "km/h"


async def test_a_parameter_registered_as_mph_moves_to_kmh_with_its_lines(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, fresh_params
):
    """Fable F1-2/F2-4: an upgraded install's SPEED row says mph. Lines are
    compared in the stored unit, so they scale with it, unrounded."""
    await fresh_params("SPEED")
    db_session.add(
        LiveLinkParameter(param_key="SPEED", unit="mph", param_class="speed", warning_max=80.0)
    )
    _vin, device, _token = await _linked(db_session, make_livelink_vehicle, "t3line")
    device_id = device.device_id

    await _post(client, _boot(device_id, SPEED_MPH, SPEED=50))

    param = await _param(db_session, "SPEED")
    assert param.unit == "km/h"
    assert param.warning_max == pytest.approx(80 * 1.609344)
    assert param.warning_min is None
    assert param.critical_min is None
    assert await _values(db_session, device_id, "SPEED") == [pytest.approx(KMH_50_MPH)]


# --- R5: a unit names its class ---------------------------------------------------


async def test_an_rpm_declared_as_class_speed_is_stored_as_frequency(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, fresh_params
):
    """N-2/Codex R1-F3: upstream declares `0C-EngineRPM` class `speed`; the
    `rpm` unit wins, or the speed range rejects every RPM above 350."""
    key = "0C-ENGINERPM"
    await fresh_params(key)
    _vin, device, _token = await _linked(db_session, make_livelink_vehicle, "t3rpm")
    device_id = device.device_id

    await _post(
        client,
        {
            "autopid_data": {key: 3000},
            "config": {key: {"class": "speed", "unit": "rpm"}},
            "status": {"device_id": device_id, "ecu_status": "online"},
        },
    )

    assert await _values(db_session, device_id, key) == [3000.0]
    assert (await _param(db_session, key)).param_class == "frequency"


# --- G5b-14: a telemetry-only POST means the WiFi and the ECU are on ------------------


async def test_a_telemetry_only_post_clears_a_pending_offline(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle
):
    _vin, device, token = await _linked(
        db_session,
        make_livelink_vehicle,
        "t3pend",
        ecu_status="online",
        pending_offline_at=utc_now() - timedelta(seconds=30),
    )
    device_id = device.device_id

    await _post(client, {"autopid_data": {"ENGINE_RPM": 800}}, token)

    assert (await _device(db_session, device_id)).pending_offline_at is None


async def test_a_telemetry_only_post_in_contact_mode_starts_a_session(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
):
    await keep_rows("livelink_session_boundary_mode")
    await SettingsService.set(db_session, "livelink_session_boundary_mode", "contact")
    _vin, device, token = await _linked(
        db_session, make_livelink_vehicle, "t3cont", ecu_status="offline"
    )
    device_id = device.device_id

    await _post(client, {"autopid_data": {"ENGINE_RPM": 800}}, token)

    assert (await _device(db_session, device_id)).ecu_status == "online"
    sessions = await db_session.execute(
        select(DriveSession).where(DriveSession.device_id == device_id)
    )
    assert len(sessions.scalars().all()) == 1


# --- D4a: a new device notifies once ---------------------------------------------


class _Recorder:
    """A notification service that keeps what it was asked to send."""

    service_name = "recorder"

    def __init__(self, sent: list[str]) -> None:
        self.sent = sent

    async def send(self, title: str, message: str, **_: Any) -> bool:
        self.sent.append(title)
        return True

    async def send_with_retry(self, title: str, message: str, **_: Any) -> bool:
        return await self.send(title, message)

    async def close(self) -> None:
        return None


@pytest.fixture
def sent() -> Any:
    """Titles the dispatcher sent, with one stand-in service switched on."""
    titles: list[str] = []
    with (
        patch(
            "app.services.notifications.dispatcher.NotificationDispatcher._has_any_service_enabled",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "app.services.notifications.dispatcher.NotificationDispatcher._get_enabled_services",
            new=AsyncMock(side_effect=lambda: [_Recorder(titles)]),
        ),
    ):
        yield titles


NEW_DEVICE = "New LiveLink Device Discovered"


async def test_a_new_https_device_notifies_once(
    db_session: AsyncSession, client: AsyncClient, sent: list[str], keep_rows
):
    await keep_rows("livelink_notify_new_device")
    await SettingsService.set(db_session, "livelink_notify_new_device", "true")
    await db_session.commit()
    device_id = _uid("t3new")

    first = await _post(client, _boot(device_id, {}))
    await _post(client, _boot(device_id, {}))

    assert first.json()["device_new"] is True
    assert sent == [NEW_DEVICE]


async def test_no_new_device_notice_with_the_switch_off(
    db_session: AsyncSession, client: AsyncClient, sent: list[str], keep_rows
):
    """Regression guard: passes before T3 because nothing notified at all. It
    fails if the pipeline sends past the General drawer's switch."""
    await keep_rows("livelink_notify_new_device")
    await SettingsService.set(db_session, "livelink_notify_new_device", "false")
    await db_session.commit()

    response = await _post(client, _boot(_uid("t3quiet"), {}))

    assert response.json()["device_new"] is True
    assert sent == []


async def test_a_new_mqtt_device_notifies_too(db_session: AsyncSession, sent: list[str], keep_rows):
    """A-5: the same switch had no caller on any path."""
    await keep_rows("livelink_notify_new_device")
    await SettingsService.set(db_session, "livelink_notify_new_device", "true")
    await db_session.commit()
    device_id = _uid("t3mq")

    await ingest(
        WicanModule(),
        MqttEnvelope(f"wican/{device_id}/can/status", json.dumps({"status": "online"}).encode()),
        db_session,
    )
    await db_session.commit()

    assert sent == [NEW_DEVICE]
    assert (await _device(db_session, device_id)).vin is None


# --- the response contract ---------------------------------------------------------


async def test_the_response_keys_are_unchanged(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle
):
    """Regression guard: the route's keys and values are what WiCAN got before."""
    _vin, device, _token = await _linked(db_session, make_livelink_vehicle, "t3keys")

    response = await _post(
        client,
        {
            "autopid_data": {"ENGINE_RPM": 900, "DIAGNOSTIC_TROUBLE_CODES": "P0301, P0420"},
            "config": {},
            "status": {"device_id": device.device_id, "ecu_status": "online"},
        },
    )

    body = response.json()
    assert response.status_code == 202
    assert set(body) == {
        "status",
        "timestamp",
        "device_id",
        "device_new",
        "device_linked",
        "parameters_stored",
        "dtcs_recorded",
    }
    assert body["status"] == "accepted"
    assert body["device_id"] == device.device_id
    assert (body["device_new"], body["device_linked"]) == (False, True)
    assert (body["parameters_stored"], body["dtcs_recorded"]) == (1, 2)


# --- fix round 1: unlinked and disabled devices on telemetry-only POSTs ------------


async def test_an_unlinked_devices_telemetry_only_post_keeps_it_online(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle
):
    """Onboarding: a discovered device posts every cycle, but its status POST
    comes once per boot. Without the bump the offline sweep marks it offline
    and sends an offline alert right after the new-device notice."""
    seen = utc_now() - timedelta(hours=1)
    _vin, device, token = await _linked(
        db_session, make_livelink_vehicle, "t3unl", device_status="offline", last_seen=seen
    )
    device.vin = None
    device_id = device.device_id
    await db_session.commit()

    await _post(client, {"autopid_data": {"ENGINE_RPM": 800}}, token)

    after = await _device(db_session, device_id)
    assert after.device_status == "online"
    assert after.last_seen is not None and after.last_seen > seen


async def test_an_unlinked_device_stores_nothing_from_a_telemetry_only_post(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, keep_rows
):
    """Regression guard for the link rule: the status update runs, and the
    `not device.vin` return after it still keeps telemetry, codes, sessions
    and threshold alerts out. Contact mode, so a session would open if the
    ECU signal reached the session service."""
    await keep_rows("livelink_session_boundary_mode")
    await SettingsService.set(db_session, "livelink_session_boundary_mode", "contact")
    _vin, device, token = await _linked(
        db_session, make_livelink_vehicle, "t3unl", ecu_status="offline"
    )
    device.vin = None
    device_id = device.device_id
    await db_session.commit()

    with patch(
        "app.services.telemetry_service.TelemetryService.check_thresholds", new_callable=AsyncMock
    ) as thresholds:
        response = await _post(
            client,
            {"autopid_data": {"SPEED": 60, "DIAGNOSTIC_TROUBLE_CODES": "P0301"}},
            token,
        )

    assert "processing_error" not in response.json()
    assert "parameters_stored" not in response.json()
    assert await _values(db_session, device_id, "SPEED") == []
    dtcs = await db_session.execute(select(VehicleDTC).where(VehicleDTC.device_id == device_id))
    assert dtcs.scalars().all() == []
    sessions = await db_session.execute(
        select(DriveSession).where(DriveSession.device_id == device_id)
    )
    assert sessions.scalars().all() == []
    thresholds.assert_not_awaited()


async def test_a_disabled_devices_telemetry_only_post_is_answered_disabled(
    db_session: AsyncSession, client: AsyncClient, make_livelink_vehicle, fresh_params
):
    """A-4 on the telemetry-only path: its own token still names it, so it is
    told it's disabled, stores nothing, writes no status, and still records a
    `config` it sends."""
    await fresh_params("SPEED")
    seen = utc_now() - timedelta(hours=1)
    _vin, device, token = await _linked(
        db_session, make_livelink_vehicle, "t3dto", device_status="offline", last_seen=seen
    )
    device.enabled = False
    device_id = device.device_id
    await db_session.commit()

    response = await _post(
        client,
        {"autopid_data": {"SPEED": 50}, "config": {"SPEED": {"unit": "mph"}}},
        token,
    )

    assert response.json()["status"] == "disabled"
    assert await _values(db_session, device_id, "SPEED") == []
    after = await _device(db_session, device_id)
    assert (after.device_status, after.last_seen) == ("offline", seen)
    assert await _units(db_session, device_id) == {"SPEED": ("mph", "speed", "wire")}

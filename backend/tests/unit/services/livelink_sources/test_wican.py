"""WiCAN parsing. Pure: no database."""

import pytest

from app.services.livelink_sources.base import (
    Capability,
    InferSession,
    MqttEnvelope,
    StatusTransition,
)
from app.services.livelink_sources.wican import WicanModule

M = WicanModule()


def test_declares_the_expected_capabilities():
    assert Capability.DRIVE_SESSION in M.capabilities
    assert Capability.ODOMETER in M.capabilities
    assert Capability.AUTO_DISCOVER in M.capabilities


def test_storage_policy_matches_todays_wican_behavior():
    assert M.storage_policy.latest == "always"
    assert M.storage_policy.sync_odometer is True
    assert M.storage_policy.observe_movement is True
    assert M.storage_policy.apply_storage_interval is True


@pytest.mark.asyncio
async def test_parses_a_status_message_into_a_status_transition():
    batch = await M.parse(MqttEnvelope("wican/fc012ccc47bd/can/status", b'{"status": "online"}'))
    assert batch.device_key == "fc012ccc47bd"
    assert batch.session == StatusTransition(ecu_status="online")
    assert batch.ecu_status == "online"


@pytest.mark.asyncio
async def test_an_unknown_status_is_not_coerced_to_offline():
    batch = await M.parse(MqttEnvelope("wican/abc/can/status", b'{"status": "weird"}'))
    assert batch.ecu_status == "unknown"


@pytest.mark.asyncio
async def test_parses_telemetry_into_readings_with_an_inferred_session():
    batch = await M.parse(MqttEnvelope("wican/abc/can/rx", b'{"odometer": 90170.0}'))
    assert batch.session == InferSession()
    assert batch.ecu_status == "online"
    assert [r.param_key for r in batch.readings] == ["ODOMETER"]  # canonicalised in-module
    assert batch.readings[0].value == 90170.0


@pytest.mark.asyncio
async def test_parses_battery_onto_the_device_and_as_telemetry():
    batch = await M.parse(MqttEnvelope("wican/abc/battery", b'{"battery_voltage": 14.5}'))
    assert batch.battery_voltage == 14.5
    assert [r.param_key for r in batch.readings] == ["BATTERY_VOLTAGE"]
    assert batch.readings[0].unit == "V"
    assert batch.session is None


@pytest.mark.asyncio
async def test_per_message_flags_match_todays_handlers():
    """Each flag encodes one verified difference between the three handlers."""
    status = await M.parse(MqttEnvelope("wican/abc/can/status", b'{"status": "online"}'))
    battery = await M.parse(MqttEnvelope("wican/abc/battery", b'{"battery_voltage": 14.5}'))
    rx = await M.parse(MqttEnvelope("wican/abc/can/rx", b'{"odometer": 1.0}'))

    assert status.requires_link is False
    assert battery.requires_link is False
    assert rx.requires_link is True

    assert battery.clear_pending_offline is False
    assert rx.clear_pending_offline is True

    assert battery.alert_on_thresholds is False
    assert rx.alert_on_thresholds is True


@pytest.mark.asyncio
async def test_device_ids_are_normalized():
    batch = await M.parse(MqttEnvelope("wican/FC:01:2C-CC:47:BD/can/rx", b'{"x": 1}'))
    assert batch.device_key == "fc012ccc47bd"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "topic,payload",
    [
        ("wican/abc/can/rx", b"not json"),
        ("tooshort", b'{"x": 1}'),
        ("wican/abc/unknown_subtopic", b'{"x": 1}'),
    ],
)
async def test_unparseable_input_returns_none_not_an_exception(topic, payload):
    assert await M.parse(MqttEnvelope(topic, payload)) is None


@pytest.mark.asyncio
async def test_subscriptions_wildcard_the_configured_prefix(db_session):
    """WiCAN is the one module that needs a wildcard: its device ids are
    discovered at runtime, so its topics cannot be enumerated."""
    from app.services.settings_service import SettingsService

    await SettingsService.set(db_session, "livelink_mqtt_enabled", "true")
    await SettingsService.set(db_session, "livelink_mqtt_broker_host", "10.10.1.11")
    await SettingsService.set(db_session, "livelink_mqtt_topic_prefix", "wican")
    await db_session.commit()

    assert await M.subscriptions(db_session) == ["wican/+/#"]


@pytest.mark.asyncio
async def test_no_subscriptions_when_mqtt_is_disabled(db_session):
    from app.services.settings_service import SettingsService

    await SettingsService.set(db_session, "livelink_mqtt_enabled", "false")
    await db_session.commit()

    assert await M.subscriptions(db_session) == []


@pytest.mark.asyncio
async def test_a_can_rx_frame_with_no_numeric_value_is_not_a_batch():
    """A-7: `{"X": null}` used to mark the ECU online with nothing to store."""
    assert await M.parse(MqttEnvelope("wican/abc/can/rx", b'{"X": null}')) is None


@pytest.mark.asyncio
async def test_a_can_rx_nan_is_not_a_reading():
    batch = await M.parse(MqttEnvelope("wican/abc/can/rx", b'{"SPEED": NaN, "ENGINE_RPM": 800}'))
    assert [r.param_key for r in batch.readings] == ["ENGINE_RPM"]


@pytest.mark.asyncio
async def test_wican_never_claims_its_status_came_from_the_wire():
    """R1: WiCAN's `online` is synthesized from a message arriving, so a
    retained frame must never qualify for the retained-offline path."""
    for topic, payload in [
        ("wican/abc/can/status", b'{"status": "offline"}'),
        ("wican/abc/battery", b'{"battery_voltage": 14.5}'),
        ("wican/abc/can/rx", b'{"ENGINE_RPM": 800}'),
    ]:
        batch = await M.parse(MqttEnvelope(topic, payload))
        assert batch is not None and batch.status_from_wire is False

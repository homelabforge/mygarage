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


@pytest.mark.asyncio
async def test_a_can_rx_dtc_string_lands_in_dtcs_next_to_the_readings():
    batch = await M.parse(
        MqttEnvelope(
            "wican/abc/can/rx", b'{"DIAGNOSTIC_TROUBLE_CODES": "P0301, p0420", "ENGINE_RPM": 800}'
        )
    )
    assert batch.dtcs == ["P0301", "P0420"]
    assert [r.param_key for r in batch.readings] == ["ENGINE_RPM"]
    assert batch.ecu_status == "online"
    assert batch.session == InferSession()


@pytest.mark.asyncio
async def test_a_dtc_only_frame_is_a_batch_with_no_ecu_or_session_signal():
    """A code list alone is no proof the ECU is on (A-7's rule), so codes only."""
    batch = await M.parse(
        MqttEnvelope("wican/abc/can/rx", b'{"DIAGNOSTIC_TROUBLE_CODES": "P0301"}')
    )
    assert batch is not None
    assert batch.dtcs == ["P0301"]
    assert batch.readings == []
    assert batch.device_status == "online"
    assert batch.ecu_status is None
    assert batch.session is None
    assert batch.requires_link is True


@pytest.mark.asyncio
async def test_a_blank_dtc_string_with_nothing_else_is_still_no_batch():
    assert (
        await M.parse(MqttEnvelope("wican/abc/can/rx", b'{"DIAGNOSTIC_TROUBLE_CODES": " , "}'))
        is None
    )


@pytest.mark.parametrize(
    "value,expected",
    [
        ("P0301, p0420", ["P0301", "P0420"]),
        (" p0301 ,,  ,U0100 ", ["P0301", "U0100"]),
        ("P0301,p0301", ["P0301"]),
        ("", []),
        (None, []),
        (301, []),
        # Not DTC-shaped: VehicleDTC.code is String(10), and on PG an
        # over-long token raised at flush and took the frame's readings down.
        ("P0301,P0301-00-EXTENDED,NO DATA,P03,X0301,P0420", ["P0301", "P0420"]),
        ("p2a0f,U0100", ["P2A0F", "U0100"]),
    ],
)
def test_the_dtc_string_rule(value, expected):
    """One rule for both WiCAN transports.

    Split, strip, uppercase, no blanks, no repeats, DTC-shaped only.
    """
    from app.services.livelink_sources.wican import dtc_codes_from_wire

    assert dtc_codes_from_wire(value) == expected


# --- HTTPS (G5b-14): the same module parses the route's payload ------------------
# Imported inside each test: before T3 the envelope doesn't exist, and only
# these cases should fail on that.


def _https(body: dict):
    from app.schemas.livelink_ingest import WiCANPayload
    from app.services.livelink_sources.base import WicanHttpsEnvelope

    payload = WiCANPayload.model_validate(body)
    device_id = payload.status.device_id if payload.status else "aabbccddeeff"
    return WicanHttpsEnvelope(device_id=device_id, payload=payload)


@pytest.mark.asyncio
async def test_an_https_status_payload_is_a_status_transition_with_its_metadata():
    batch = await M.parse(
        _https(
            {
                "autopid_data": {"0c-EngineRPM": 900, "TS": 4, "DIAGNOSTIC_TROUBLE_CODES": "p0301"},
                "config": {"0c-EngineRPM": {"class": "speed", "unit": "rpm"}},
                "status": {
                    "device_id": "AA:BB:CC:DD:EE:FF",
                    "ecu_status": "online",
                    "hw_version": "WiCAN-OBD-PRO",
                    "fw_version": "4.50",
                    "git_version": "v4.50p",
                    "sta_ip": "10.0.0.9",
                    "rssi": -40,
                    "battery_voltage": 13.9,
                },
                "timestamp": "2026-10-10T12:00:00Z",
            }
        )
    )

    assert batch.device_key == "aabbccddeeff"
    assert batch.session == StatusTransition(ecu_status="online")
    assert (batch.device_status, batch.ecu_status) == ("online", "online")
    assert (batch.rssi, batch.sta_ip, batch.battery_voltage) == (-40, "10.0.0.9", 13.9)
    assert batch.discovery is not None
    assert (batch.discovery.hw_version, batch.discovery.fw_version) == ("WiCAN-OBD-PRO", "4.50")
    assert (batch.discovery.git_version, batch.discovery.sta_ip) == ("v4.50p", "10.0.0.9")
    assert batch.requires_link is False
    assert batch.clear_pending_offline is False
    assert batch.alert_on_thresholds is True
    assert batch.allow_discovery is True
    # Canonical key, TS dropped, and R5: the `rpm` unit beats the declared class.
    assert [(r.param_key, r.value, r.unit, r.param_class) for r in batch.readings] == [
        ("0C-ENGINERPM", 900.0, "rpm", "frequency")
    ]
    assert {k: (u.unit, u.param_class) for k, u in batch.declared_wire_units.items()} == {
        "0C-ENGINERPM": ("rpm", "frequency")
    }
    assert batch.wire_profile is True
    assert batch.dtcs == ["P0301"]
    assert batch.timestamp is not None and batch.timestamp.hour == 12


@pytest.mark.asyncio
async def test_a_status_payload_with_the_default_empty_config_is_not_a_profile():
    """Fable F4-1: `config` defaults to `{}`; `status` alone replaces nothing."""
    batch = await M.parse(_https({"autopid_data": {}, "status": {"device_id": "aabbccddeeff"}}))
    assert batch.wire_profile is False
    assert batch.declared_wire_units == {}


@pytest.mark.parametrize("bad", ["NaN", "Infinity"])
@pytest.mark.asyncio
async def test_a_non_finite_status_battery_is_left_unsaid(bad: str):
    import json

    from app.schemas.livelink_ingest import WiCANPayload
    from app.services.livelink_sources.base import WicanHttpsEnvelope

    raw = (
        '{"autopid_data": {}, "status": {"device_id": "aabbccddeeff", "battery_voltage": '
        + bad
        + "}}"
    )
    payload = WiCANPayload.model_validate(json.loads(raw))
    batch = await M.parse(WicanHttpsEnvelope(device_id="aabbccddeeff", payload=payload))
    assert batch.battery_voltage is None


@pytest.mark.asyncio
async def test_a_telemetry_only_payload_infers_the_session_like_can_rx():
    batch = await M.parse(
        _https({"autopid_data": {"SPEED": 50, "X": "junk"}, "config": {"SPEED": {"unit": "mph"}}})
    )

    assert batch.device_key == "aabbccddeeff"
    assert batch.session == InferSession()
    assert (batch.device_status, batch.ecu_status) == ("online", "online")
    assert batch.clear_pending_offline is True
    # Unlike can/rx: the only thing keeping an unlinked HTTPS device's
    # last_seen fresh between boots (fix round 1).
    assert batch.requires_link is False
    assert batch.alert_on_thresholds is True
    # Only a status payload may create a device.
    assert batch.allow_discovery is False
    assert batch.discovery is None
    assert batch.wire_profile is False
    assert [(r.param_key, r.value, r.unit, r.param_class) for r in batch.readings] == [
        ("SPEED", 50.0, "mph", "speed")
    ]


@pytest.mark.asyncio
async def test_a_telemetry_only_payload_with_nothing_in_it_says_nothing_about_the_ecu():
    """A-7's rule for HTTPS: no value is no proof the ECU is on."""
    batch = await M.parse(_https({"autopid_data": {"DIAGNOSTIC_TROUBLE_CODES": "P0420"}}))

    assert batch.dtcs == ["P0420"]
    assert batch.readings == []
    assert batch.device_status == "online"
    assert batch.requires_link is False
    assert (batch.ecu_status, batch.session, batch.clear_pending_offline) == (None, None, False)


def test_config_entries_that_wont_fit_the_columns_are_dropped():
    """Guards new code: a value past the column width would fail the request's
    flush on PG. Mutation-checked (drop the width test and this fails)."""
    from app.schemas.livelink_ingest import WiCANConfigEntry
    from app.services.livelink_sources.wican import wire_units_from_config

    out = wire_units_from_config(
        {
            "K" * 101: WiCANConfigEntry(unit="V"),
            "LONG_UNIT": WiCANConfigEntry(unit="u" * 21),
            "LONG_CLASS": WiCANConfigEntry(param_class="c" * 51),
            "K" * 100: WiCANConfigEntry(unit="u" * 20, param_class="c" * 50),
        }
    )
    assert list(out) == ["K" * 100]


def test_config_drops_frame_metadata_the_dtc_key_and_empty_entries():
    """Guards new code: TS/TIMESTAMP aren't telemetry, the code list isn't a
    reading, and an entry with no unit or class says nothing. Mutation-checked."""
    from app.schemas.livelink_ingest import WiCANConfigEntry
    from app.services.livelink_sources.wican import wire_units_from_config

    out = wire_units_from_config(
        {
            "ts": WiCANConfigEntry(unit="ms"),
            "TIMESTAMP": WiCANConfigEntry(unit="s"),
            "DIAGNOSTIC_TROUBLE_CODES": WiCANConfigEntry(param_class="dtc"),
            "BLANK": WiCANConfigEntry(unit="  ", param_class=""),
            " coolant temp ": WiCANConfigEntry(unit="°C"),
        }
    )
    assert {k: (v.unit, v.param_class) for k, v in out.items()} == {
        "COOLANT_TEMP": ("°C", "temperature")
    }

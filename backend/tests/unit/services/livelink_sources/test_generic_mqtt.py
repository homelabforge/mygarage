"""Table-driven MQTT mapping: coercion, transform, JSON paths, status role."""

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.models.livelink_topic_map import LiveLinkTopicMap
from app.services.livelink_sources.base import Capability, MqttEnvelope
from app.services.livelink_sources.generic_mqtt import GenericMqttModule

T = "mygarage/rv/propane/tank1/level_percent"


@pytest_asyncio.fixture(autouse=True)
async def _empty_topic_maps(db_session):
    """Leave `livelink_topic_maps` empty before AND after every test here.

    `refresh()` loads every enabled row in the table, so a row left by an
    earlier test (or another suite) lands in the cache and breaks the exact
    `subscriptions() == [...]` assertions. The suite shares one database with
    no per-test rollback, so this has to be explicit.
    """
    await db_session.execute(delete(LiveLinkTopicMap))
    await db_session.commit()
    yield
    await db_session.execute(delete(LiveLinkTopicMap))
    await db_session.commit()


def test_does_not_declare_drive_session():
    """THE structural guard: propane must never open a drive session."""
    assert Capability.DRIVE_SESSION not in GenericMqttModule.capabilities
    assert GenericMqttModule.capabilities == frozenset({Capability.TELEMETRY})


def test_does_not_declare_auto_discover():
    """Topics carry no device identity, so devices are created explicitly."""
    assert Capability.AUTO_DISCOVER not in GenericMqttModule.capabilities


@pytest.fixture
async def mapped(db_session):
    db_session.add(
        LiveLinkTopicMap(device_id="gw01", topic=T, param_key="PROPANE_T1_LEVEL_PCT", unit="%")
    )
    await db_session.commit()
    mod = GenericMqttModule()
    await mod.refresh(db_session)
    return mod


@pytest.mark.asyncio
async def test_subscriptions_are_the_exact_mapped_topics(db_session, mapped):
    assert await mapped.subscriptions(db_session) == [T]


@pytest.mark.asyncio
async def test_a_bare_scalar_payload_becomes_a_reading(mapped):
    batch = await mapped.parse(MqttEnvelope(T, b"71"))
    assert batch.device_key == "gw01"
    assert batch.readings[0].param_key == "PROPANE_T1_LEVEL_PCT"
    assert batch.readings[0].value == 71.0
    assert batch.readings[0].unit == "%"
    assert batch.session is None


@pytest.mark.asyncio
async def test_an_unmapped_topic_returns_none(mapped):
    assert await mapped.parse(MqttEnvelope("nobody/cares", b"1")) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,expected",
    [
        (b"ON", 1.0),
        (b"on", 1.0),
        (b"true", 1.0),
        (b"ONLINE", 1.0),
        (b"open", 1.0),
        (b"YES", 1.0),
        (b"1", 1.0),
        (b"OFF", 0.0),
        (b"false", 0.0),
        (b"offline", 0.0),
        (b"closed", 0.0),
        (b"no", 0.0),
        (b"0", 0.0),
    ],
)
async def test_non_numeric_payloads_are_coerced(mapped, payload, expected):
    batch = await mapped.parse(MqttEnvelope(T, payload))
    assert batch.readings[0].value == expected


@pytest.mark.asyncio
async def test_an_uncoercible_payload_is_dropped(mapped):
    batch = await mapped.parse(MqttEnvelope(T, b"192.168.1.5"))
    assert batch is None or batch.readings == []


@pytest.mark.asyncio
async def test_scale_and_offset_are_applied(db_session):
    db_session.add(
        LiveLinkTopicMap(
            device_id="d", topic="t/f", param_key="TEMP_C", scale=0.555556, value_offset=-17.7778
        )
    )
    await db_session.commit()
    mod = GenericMqttModule()
    await mod.refresh(db_session)
    batch = await mod.parse(MqttEnvelope("t/f", b"212"))
    assert batch.readings[0].value == pytest.approx(100.0, abs=0.01)


@pytest.mark.asyncio
async def test_a_json_payload_is_read_by_dotted_path(db_session):
    db_session.add(
        LiveLinkTopicMap(device_id="d", topic="t/j", param_key="V", value_path="battery.voltage")
    )
    await db_session.commit()
    mod = GenericMqttModule()
    await mod.refresh(db_session)
    batch = await mod.parse(MqttEnvelope("t/j", b'{"battery": {"voltage": 12.7}}'))
    assert batch.readings[0].value == 12.7


@pytest.mark.asyncio
async def test_a_missing_json_path_is_dropped(db_session):
    db_session.add(LiveLinkTopicMap(device_id="d", topic="t/j", param_key="V", value_path="nope"))
    await db_session.commit()
    mod = GenericMqttModule()
    await mod.refresh(db_session)
    batch = await mod.parse(MqttEnvelope("t/j", b'{"battery": 1}'))
    assert batch is None or batch.readings == []


@pytest.mark.asyncio
async def test_a_status_role_sets_device_status_not_a_reading(db_session):
    db_session.add(
        LiveLinkTopicMap(
            device_id="gw01", topic="mygarage/rv/status", role="status", param_key=None
        )
    )
    await db_session.commit()
    mod = GenericMqttModule()
    await mod.refresh(db_session)
    batch = await mod.parse(MqttEnvelope("mygarage/rv/status", b"offline"))
    assert batch.device_status == "offline"
    assert batch.readings == []


@pytest.mark.asyncio
async def test_a_telemetry_batch_leaves_device_status_alone(mapped):
    """R1-H5: a retained replay must not resurrect a gateway the LWT killed."""
    batch = await mapped.parse(MqttEnvelope(T, b"71"))
    assert batch.device_status is None
    assert batch.requires_link is True
    assert batch.alert_on_thresholds is True


@pytest.mark.asyncio
async def test_a_topic_claimed_by_two_devices_is_ignored_entirely(db_session):
    """R1-H2: fail closed rather than attribute readings to the wrong vehicle."""
    db_session.add(LiveLinkTopicMap(device_id="devA", topic="shared/t", param_key="A"))
    db_session.add(LiveLinkTopicMap(device_id="devB", topic="shared/t", param_key="B"))
    await db_session.commit()
    mod = GenericMqttModule()
    await mod.refresh(db_session)
    assert "shared/t" not in await mod.subscriptions(db_session)
    assert await mod.parse(MqttEnvelope("shared/t", b"1")) is None


@pytest.mark.asyncio
async def test_disabled_rows_are_not_subscribed_or_parsed(db_session):
    db_session.add(LiveLinkTopicMap(device_id="d", topic="t/off", param_key="P", enabled=False))
    await db_session.commit()
    mod = GenericMqttModule()
    await mod.refresh(db_session)
    assert await mod.subscriptions(db_session) == []
    assert await mod.parse(MqttEnvelope("t/off", b"1")) is None


@pytest.mark.asyncio
async def test_one_topic_feeding_two_params_yields_two_readings(db_session):
    db_session.add(LiveLinkTopicMap(device_id="d", topic="t/j", param_key="A", value_path="a"))
    db_session.add(LiveLinkTopicMap(device_id="d", topic="t/j", param_key="B", value_path="b"))
    await db_session.commit()
    mod = GenericMqttModule()
    await mod.refresh(db_session)
    batch = await mod.parse(MqttEnvelope("t/j", b'{"a": 1, "b": 2}'))
    assert sorted(r.param_key for r in batch.readings) == ["A", "B"]


@pytest.mark.parametrize("raw", ["nan", "NaN", "inf", "-inf", "Infinity", "1e400"])
def test_coerce_refuses_non_finite_values(raw):
    """A-3: float() takes all of these, and NaN hits a NOT NULL on SQLite."""
    from app.services.livelink_sources.generic_mqtt import _coerce

    assert _coerce(raw) is None


@pytest.mark.asyncio
async def test_a_json_nan_is_dropped(db_session):
    db_session.add(LiveLinkTopicMap(device_id="d", topic="t/j", param_key="V", value_path="v"))
    await db_session.commit()
    mod = GenericMqttModule()
    await mod.refresh(db_session)
    batch = await mod.parse(MqttEnvelope("t/j", b'{"v": NaN}'))
    assert batch is None


@pytest.mark.asyncio
async def test_a_status_role_batch_says_its_status_came_from_the_wire(db_session):
    """R1: the retained-offline path keys on this, not on device_status alone."""
    db_session.add(
        LiveLinkTopicMap(
            device_id="gw01", topic="mygarage/rv/status", role="status", param_key=None
        )
    )
    await db_session.commit()
    mod = GenericMqttModule()
    await mod.refresh(db_session)
    batch = await mod.parse(MqttEnvelope("mygarage/rv/status", b"offline"))
    assert batch.status_from_wire is True


@pytest.mark.asyncio
async def test_a_telemetry_batch_does_not_claim_a_wire_status(mapped):
    batch = await mapped.parse(MqttEnvelope(T, b"71"))
    assert batch.status_from_wire is False

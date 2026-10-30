"""The source-module contract: shapes only, no database."""

import pytest

from app.services.livelink_sources.base import (
    BaseSourceModule,
    Capability,
    ExplicitSession,
    HttpEnvelope,
    InferSession,
    IngestBatch,
    MqttEnvelope,
    Reading,
    StatusTransition,
    StoragePolicy,
)


class _Fake(BaseSourceModule):
    kind = "fake"
    capabilities = frozenset({Capability.TELEMETRY})

    async def parse(self, env):
        return IngestBatch(device_key="dev1", readings=[Reading("X", 1.0)])


def test_abstract_module_cannot_be_instantiated():
    with pytest.raises(TypeError):
        BaseSourceModule()  # type: ignore[abstract]


@pytest.mark.asyncio
async def test_concrete_module_parses_to_a_batch():
    batch = await _Fake().parse(MqttEnvelope(topic="a/b", payload=b"1"))
    assert batch.device_key == "dev1"
    assert batch.readings == [Reading("X", 1.0)]
    assert batch.session is None
    assert batch.readings[0].unit is None


@pytest.mark.asyncio
async def test_modules_declare_no_subscriptions_by_default():
    assert await _Fake().subscriptions(None) == []


def test_default_storage_policy_is_the_safe_one():
    p = StoragePolicy()
    assert p.latest == "always"
    assert p.sync_odometer is False
    assert p.observe_movement is False


def test_session_signals_are_distinguishable():
    assert InferSession() != ExplicitSession(external_id="7")
    assert ExplicitSession(external_id="7").external_id == "7"
    assert StatusTransition(ecu_status="offline").ecu_status == "offline"
    assert StatusTransition(ecu_status="online") != InferSession()


def test_envelopes_are_distinct_types():
    assert isinstance(MqttEnvelope("t", b"p"), MqttEnvelope)
    assert isinstance(HttpEnvelope("tok", {}), HttpEnvelope)
    assert not isinstance(HttpEnvelope("tok", {}), MqttEnvelope)


def test_readings_are_hashable_so_batches_can_be_compared():
    assert {Reading("X", 1.0)} == {Reading("X", 1.0)}

"""Registry behavior: lookup, kind validation, subscription fan-out."""

import pytest

from app.services.livelink_sources import registry
from app.services.livelink_sources.base import (
    BaseSourceModule,
    Capability,
    IngestBatch,
)


class _Alpha(BaseSourceModule):
    kind = "alpha"
    capabilities = frozenset({Capability.TELEMETRY})
    own_param_keys = frozenset({"ALPHA_TOTAL"})

    async def subscriptions(self, db):
        return ["a/one", "a/two"]

    async def parse(self, env):
        return IngestBatch(device_key="a")


class _Beta(BaseSourceModule):
    kind = "beta"
    capabilities = frozenset({Capability.TELEMETRY, Capability.DRIVE_SESSION})

    async def parse(self, env):
        return IngestBatch(device_key="b")


@pytest.fixture
def reg():
    r = registry.SourceRegistry()
    r.register(_Alpha())
    r.register(_Beta())
    return r


def test_lookup_by_kind(reg):
    assert isinstance(reg.get_module("alpha"), _Alpha)
    assert reg.get_module("nope") is None


def test_valid_kinds_is_the_source_of_truth(reg):
    assert reg.valid_kinds() == frozenset({"alpha", "beta"})


def test_registering_a_duplicate_kind_is_an_error(reg):
    with pytest.raises(ValueError, match="alpha"):
        reg.register(_Alpha())


@pytest.mark.asyncio
async def test_subscriptions_map_topics_to_their_owning_module(reg):
    subs = await reg.mqtt_subscriptions(None)
    assert set(subs) == {"a/one", "a/two"}
    assert isinstance(subs["a/one"], _Alpha)


@pytest.mark.asyncio
async def test_http_only_modules_contribute_no_topics(reg):
    subs = await reg.mqtt_subscriptions(None)
    assert not any(isinstance(m, _Beta) for m in subs.values())


@pytest.mark.asyncio
async def test_a_module_claiming_anothers_topic_is_an_error():
    class _Clash(BaseSourceModule):
        kind = "clash"
        capabilities = frozenset({Capability.TELEMETRY})

        async def subscriptions(self, db):
            return ["a/one"]

        async def parse(self, env):
            return None

    r = registry.SourceRegistry()
    r.register(_Alpha())
    r.register(_Clash())
    with pytest.raises(ValueError, match="a/one"):
        await r.mqtt_subscriptions(None)


def test_the_default_registry_has_the_shipped_modules():
    assert registry.default_registry().valid_kinds() == frozenset(
        {"wican", "torque", "generic_mqtt"}
    )


def test_foreign_param_keys_are_what_the_other_modules_name_for_themselves(reg):
    """A WiCAN's odometer scan skips these (FW-A-r4a). A module with no fixed
    vocabulary contributes nothing, and no module sees its own keys as foreign.
    Red on 63640d97 (no such method)."""
    assert reg.foreign_param_keys("beta") == frozenset({"ALPHA_TOTAL"})
    assert reg.foreign_param_keys("alpha") == frozenset()


def test_the_default_registry_knows_torques_own_keys():
    """Torque's total is Torque's; the standard PID aliases are everyone's."""
    foreign = registry.default_registry().foreign_param_keys("wican")
    assert "TORQUE_ODOMETER" in foreign
    assert "SPEED" not in foreign
    assert registry.default_registry().foreign_param_keys("torque") == frozenset()


def test_a_policy_that_reaches_sessions_without_the_capability_is_refused():
    """Closes the back door: observe_movement drives SessionService via store_telemetry."""
    from app.services.livelink_sources.base import StoragePolicy

    class _Sneaky(BaseSourceModule):
        kind = "sneaky"
        capabilities = frozenset({Capability.TELEMETRY})
        storage_policy = StoragePolicy(observe_movement=True)

        async def parse(self, env):
            return None

    with pytest.raises(ValueError, match="DRIVE_SESSION"):
        registry.SourceRegistry().register(_Sneaky())


def test_sync_odometer_without_the_capability_is_refused():
    from app.services.livelink_sources.base import StoragePolicy

    class _Sneaky2(BaseSourceModule):
        kind = "sneaky2"
        capabilities = frozenset({Capability.TELEMETRY})
        storage_policy = StoragePolicy(sync_odometer=True)

        async def parse(self, env):
            return None

    with pytest.raises(ValueError, match="ODOMETER"):
        registry.SourceRegistry().register(_Sneaky2())


@pytest.mark.parametrize(
    "pattern,topic,expected",
    [
        ("a/one", "a/one", True),
        ("a/one", "a/two", False),
        ("wican/+/can/rx", "wican/abc/can/rx", True),
        ("wican/+/can/rx", "wican/abc/def/can/rx", False),
        ("wican/+/#", "wican/abc/can/rx", True),
        ("wican/+/#", "wican/abc", False),
        ("wican/#", "wican/abc/can/rx", True),
        ("a/b", "a/b/c", False),
        ("a/b/c", "a/b", False),
    ],
)
def test_topic_matches(pattern, topic, expected):
    assert registry.topic_matches(pattern, topic) is expected


@pytest.mark.asyncio
async def test_resolve_topic_prefers_an_exact_match_over_a_wildcard(reg):
    class _Wild(BaseSourceModule):
        kind = "wild"
        capabilities = frozenset({Capability.TELEMETRY})

        async def subscriptions(self, db):
            return ["a/#"]

        async def parse(self, env):
            return None

    r = registry.SourceRegistry()
    r.register(_Alpha())  # exact: a/one, a/two
    r.register(_Wild())  # wildcard: a/#
    subs = await r.mqtt_subscriptions(None)
    assert isinstance(r.resolve_topic("a/one", subs), _Alpha)
    assert isinstance(r.resolve_topic("a/three", subs), _Wild)
    assert r.resolve_topic("z/nine", subs) is None

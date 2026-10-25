"""Source module registry.

This is the single source of truth for which `livelink_devices.kind` values
are valid, replacing the closed `'wican' | 'torque'` comment on the model.

Deliberately NOT modelled on `app/services/poi/registry.py`, which registers
providers through a five-branch if/elif chain that grows with every provider.
This is a flat dict, so adding a source is one `register()` call.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.livelink_sources.base import BaseSourceModule, Capability

logger = logging.getLogger(__name__)


def topic_matches(pattern: str, topic: str) -> bool:
    """MQTT topic-filter match, supporting `+` (one level) and `#` (rest).

    Needed only because WiCAN subscribes with a wildcard: its device ids are
    discovered at runtime so its topics cannot be enumerated. Every
    `generic_mqtt` topic is exact by design, precisely so the common path is a
    dict lookup and there is no way to configure a `#` that firehoses the
    broker into the database.
    """
    pattern_parts = pattern.split("/")
    topic_parts = topic.split("/")
    for i, segment in enumerate(pattern_parts):
        if segment == "#":
            # `#` matches the remainder, but must have at least one level.
            return i < len(topic_parts)
        if i >= len(topic_parts):
            return False
        if segment != "+" and segment != topic_parts[i]:
            return False
    return len(pattern_parts) == len(topic_parts)


class SourceRegistry:
    """Holds one instance per source kind."""

    def __init__(self) -> None:
        self._modules: dict[str, BaseSourceModule] = {}

    def register(self, module: BaseSourceModule) -> None:
        """Add a module, enforcing the capability/policy invariant.

        The capability gate has a BACK DOOR without this check.
        `StoragePolicy(observe_movement=True)` or `sync_odometer=True` routes
        `store_readings` into `store_telemetry`, which calls `_observe_movement`
        and `_refresh_closed_session` internally. A module could therefore drive
        session machinery WITHOUT declaring DRIVE_SESSION, which is exactly the
        thing the capability design claims is structurally impossible.

        So the claim is enforced here rather than merely asserted in prose.
        """
        if module.kind in self._modules:
            raise ValueError(f"Duplicate source kind: {module.kind}")
        policy = module.storage_policy
        if policy.observe_movement and Capability.DRIVE_SESSION not in module.capabilities:
            raise ValueError(
                f"{module.kind}: observe_movement reaches SessionService via "
                "store_telemetry, so it requires the DRIVE_SESSION capability"
            )
        if policy.sync_odometer and Capability.ODOMETER not in module.capabilities:
            raise ValueError(f"{module.kind}: sync_odometer requires the ODOMETER capability")
        self._modules[module.kind] = module

    def get_module(self, kind: str) -> BaseSourceModule | None:
        """The module for a device kind, or None if unknown."""
        return self._modules.get(kind)

    def capabilities_for(self, kind: str) -> frozenset[Capability]:
        """What a device kind can do. A kind with no module can do nothing.

        Never raises, on purpose: a module removed in a later release leaves
        its rows behind, and the offline sweep runs every device under one
        `try`, so one orphan must not stop the rest (Fable F5-3).
        """
        module = self._modules.get(kind)
        return module.capabilities if module is not None else frozenset()

    def all_modules(self) -> list[BaseSourceModule]:
        """Every registered module."""
        return list(self._modules.values())

    def valid_kinds(self) -> frozenset[str]:
        """Every valid `livelink_devices.kind` value."""
        return frozenset(self._modules)

    def foreign_param_keys(self, kind: str) -> frozenset[str]:
        """The keys every OTHER module names for itself (`own_param_keys`).

        A device of ``kind`` never sent one, so a per-vehicle read (the latest
        table has no device id) can tell another source's key from its own: a
        WiCAN's odometer scan skips them (FW-A-r4a). A new source joins by
        declaring its vocabulary; nothing here names a kind.
        """
        keys: frozenset[str] = frozenset()
        for module in self._modules.values():
            if module.kind != kind:
                keys |= module.own_param_keys
        return keys

    async def mqtt_subscriptions(self, db: AsyncSession | None) -> dict[str, BaseSourceModule]:
        """Exact topic to owning module, across all registered modules.

        Raises if two modules claim the same topic: that is a configuration
        error we want loud at subscribe time, not a message silently routed to
        whichever module happened to register first.
        """
        mapping: dict[str, BaseSourceModule] = {}
        for module in self._modules.values():
            for topic in await module.subscriptions(db):
                if topic in mapping:
                    raise ValueError(
                        f"Topic {topic} claimed by both {mapping[topic].kind} and {module.kind}"
                    )
                mapping[topic] = module
        return mapping

    def resolve_topic(
        self, topic: str, subs: dict[str, BaseSourceModule]
    ) -> BaseSourceModule | None:
        """Which module owns a received topic.

        Exact match first: that is every `generic_mqtt` row and it is a dict
        lookup at 79,000 messages/day. Wildcard patterns are checked only on a
        miss, and today only WiCAN registers one.
        """
        exact = subs.get(topic)
        if exact is not None:
            return exact
        for pattern, module in subs.items():
            if ("+" in pattern or "#" in pattern) and topic_matches(pattern, topic):
                return module
        return None


@lru_cache(maxsize=1)
def default_registry() -> SourceRegistry:
    """The process-wide registry with every shipped module."""
    from app.services.livelink_sources.generic_mqtt import GenericMqttModule
    from app.services.livelink_sources.torque import TorqueModule
    from app.services.livelink_sources.wican import WicanModule

    reg = SourceRegistry()
    reg.register(WicanModule())
    reg.register(TorqueModule())
    reg.register(GenericMqttModule())
    return reg

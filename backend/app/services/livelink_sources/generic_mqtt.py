"""Any MQTT device, driven entirely by the livelink_topic_maps table.

This is what makes "add the device you own" a UI action rather than a pull
request. Mopeka propane arrives through here with no Mopeka-specific code.

Declares TELEMETRY only. Not declaring DRIVE_SESSION is the structural reason
a propane sensor cannot open a drive session on a parked trailer: the pipeline
has no reachable path to SessionService for this module.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_topic_map import LiveLinkTopicMap
from app.schemas.livelink import DeviceStatusType
from app.services.livelink_sources.base import (
    BaseSourceModule,
    Capability,
    IngestBatch,
    MqttEnvelope,
    Reading,
    StoragePolicy,
)
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

#: Payloads that are not numbers but are still values. Lowercased before lookup.
#: This is what makes ESPHome `availability` and LWT `status` topics work
#: without special-casing any vendor.
_TRUTHY = {"on", "true", "online", "open", "yes", "1"}
_FALSY = {"off", "false", "offline", "closed", "no", "0"}


@dataclass(frozen=True)
class _Entry:
    """One cached mapping row."""

    device_id: str
    role: str
    param_key: str | None
    value_path: str | None
    unit: str | None
    param_class: str | None
    scale: float
    value_offset: float


def _coerce(raw: str) -> float | None:
    """A payload to a float, or None when it is not a value at all.

    NaN and infinity are not values: float() takes "nan", "inf" and "1e400",
    and a NaN hits the latest table's NOT NULL on SQLite. Same rule as
    Torque's `_to_float`.
    """
    try:
        value = float(raw)
    except ValueError:
        pass
    else:
        return value if math.isfinite(value) else None
    lowered = raw.strip().lower()
    if lowered in _TRUTHY:
        return 1.0
    if lowered in _FALSY:
        return 0.0
    return None


def _dig(payload: str, path: str) -> float | None:
    """Read a dotted path out of a JSON payload."""
    try:
        node = json.loads(payload)
    except json.JSONDecodeError:
        return None
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return _coerce(str(node))


class GenericMqttModule(BaseSourceModule):
    """A device described by rows, not code."""

    kind = "generic_mqtt"
    #: TELEMETRY only, deliberately. See the module docstring.
    capabilities = frozenset({Capability.TELEMETRY})
    storage_policy = StoragePolicy(
        latest="always",
        apply_storage_interval=True,
        sync_odometer=False,
        observe_movement=False,
    )

    def __init__(self) -> None:
        self._cache: dict[str, list[_Entry]] = {}

    async def refresh(self, db: AsyncSession) -> None:
        """Reload the topic map into memory.

        The cache is what keeps `parse` pure and fast: a query per message at
        79,000 messages/day would be neither.
        """
        rows = (
            (await db.execute(select(LiveLinkTopicMap).where(LiveLinkTopicMap.enabled.is_(True))))
            .scalars()
            .all()
        )
        cache: dict[str, list[_Entry]] = {}
        owner: dict[str, str] = {}
        disputed: set[str] = set()
        for row in rows:
            claimed = owner.setdefault(row.topic, row.device_id)
            if claimed != row.device_id:
                # Fail closed. parse() attributes a batch to entries[0], so a
                # disputed topic would write one device's readings against
                # another device's vehicle. Task 12 rejects this at write time;
                # this catches rows that predate the rule or came from a direct
                # database edit.
                disputed.add(row.topic)
                continue
            cache.setdefault(row.topic, []).append(
                _Entry(
                    device_id=row.device_id,
                    role=row.role,
                    param_key=row.param_key,
                    value_path=row.value_path,
                    unit=row.unit,
                    param_class=row.param_class,
                    scale=float(row.scale if row.scale is not None else Decimal(1)),
                    value_offset=float(
                        row.value_offset if row.value_offset is not None else Decimal(0)
                    ),
                )
            )
        for topic in disputed:
            cache.pop(topic, None)
            logger.error(
                "Topic %s is mapped to more than one device; ignoring it entirely",
                sanitize_for_log(topic),
            )
        self._cache = cache

    async def subscriptions(self, db: AsyncSession) -> list[str]:
        """Every enabled mapped topic, exactly. Never a wildcard."""
        await self.refresh(db)
        return sorted(self._cache)

    async def parse(self, env) -> IngestBatch | None:
        if not isinstance(env, MqttEnvelope):
            return None
        entries = self._cache.get(env.topic)
        if not entries:
            return None

        try:
            raw = env.payload.decode("utf-8").strip()
        except UnicodeDecodeError:
            logger.debug("Undecodable payload on %s", sanitize_for_log(env.topic))
            return None

        device_id = entries[0].device_id
        readings: list[Reading] = []
        device_status: DeviceStatusType | None = None

        for entry in entries:
            value = _dig(raw, entry.value_path) if entry.value_path else _coerce(raw)
            if value is None:
                logger.debug("Dropping unmappable payload on %s", sanitize_for_log(env.topic))
                continue
            if entry.role == "status":
                device_status = "online" if value else "offline"
                continue
            if entry.param_key is None:
                continue
            readings.append(
                Reading(
                    param_key=entry.param_key,
                    value=value * entry.scale + entry.value_offset,
                    unit=entry.unit,
                    param_class=entry.param_class,
                )
            )

        if not readings and device_status is None:
            return None
        # The status came off a status topic, so a retained `offline` here is
        # the LWT and still counts (R1).
        status_from_wire = device_status is not None
        # A live reading means it's talking, same as WiCAN's `can/rx`. That's
        # what gets a sensor with no status topic into the offline sweep (D5a),
        # and it brings back a device whose retained `online` birth R1 dropped.
        # Not over a status the same message gave: `{"available": false,
        # "level": 42}` is offline (Fable F3-4). Retained telemetry never gets
        # this far anyway, R1 drops it in `ingest` before the device is touched.
        if readings and not status_from_wire and not env.retain:
            device_status = "online"
        return IngestBatch(
            device_key=device_id,
            readings=readings,
            device_status=device_status,
            status_from_wire=status_from_wire,
            # No AUTO_DISCOVER: a generic device is created explicitly, so an
            # unmapped or unlinked one stores nothing.
            requires_link=True,
            # Low-tank alerting is the point of this project, so unlike Torque
            # this source DOES opt in to threshold checks.
            alert_on_thresholds=True,
        )

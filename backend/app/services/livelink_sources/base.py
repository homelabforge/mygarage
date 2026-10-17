"""The contract every LiveLink telemetry source implements.

A module is a PURE parser: wire format in, normalized `IngestBatch` out. It
performs no database work and has no side effects, which is what makes each
one testable against a payload fixture alone. All orchestration (device
resolution, session handling, storage, alerting) belongs to
`app.services.livelink_ingest`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.livelink import DeviceStatusType, ECUStatusType

if TYPE_CHECKING:
    from app.models.livelink_device import LiveLinkDevice


class Capability(Enum):
    """What a source produces.

    The pipeline has no code path that reaches SessionService, LocationService
    or odometer sync for a module that does not declare the matching
    capability. That is structural, not a guard someone has to remember: a
    propane sensor cannot open a drive session on a parked trailer.
    """

    TELEMETRY = "telemetry"
    DRIVE_SESSION = "drive_session"
    LOCATION = "location"
    DTC = "dtc"
    ODOMETER = "odometer"
    COMMANDS = "commands"
    SD_BACKFILL = "sd_backfill"
    AUTO_DISCOVER = "auto_discover"


@dataclass(frozen=True)
class MqttEnvelope:
    """One MQTT message."""

    topic: str
    payload: bytes


@dataclass(frozen=True)
class HttpEnvelope:
    """One HTTP ingest request."""

    token: str
    params: Mapping[str, str]


Envelope = MqttEnvelope | HttpEnvelope


@dataclass(frozen=True)
class Reading:
    """One parameter value. `param_key` is already canonical."""

    param_key: str
    value: float
    unit: str | None = None
    param_class: str | None = None
    #: A readable name from the source, for a key whose auto name says nothing.
    display_name: str | None = None


@dataclass(frozen=True)
class GeoPoint:
    """A GPS breadcrumb. Decimal to match the location_points columns."""

    latitude: Decimal
    longitude: Decimal
    speed: Decimal | None = None
    heading: Decimal | None = None
    altitude: Decimal | None = None


@dataclass(frozen=True)
class InferSession:
    """Data arriving at all implies the engine is running. WiCAN."""


@dataclass(frozen=True)
class StatusTransition:
    """An explicit device status message. WiCAN `can/status`.

    Distinct from `InferSession` because it carries the grace-period
    semantics: an offline sets `pending_offline_at` rather than ending the
    session outright, so a brief WiFi drop does not split one drive in two.
    """

    ecu_status: ECUStatusType


@dataclass(frozen=True)
class ExplicitSession:
    """The payload carries its own session identity. Torque."""

    external_id: str | None


SessionSignal = InferSession | StatusTransition | ExplicitSession


@dataclass(frozen=True)
class StoragePolicy:
    """How a source's readings are persisted.

    These four fields are not preferences. Each one names a real, pre-existing
    behavioral difference between the WiCAN and Torque paths, made explicit so
    the port cannot silently merge them:

    `latest`: WiCAN overwrites vehicle_telemetry_latest unconditionally
    (`_upsert_latest_value`); Torque only when strictly newer
    (`_update_latest_if_newer`), so a backfilled row never clobbers a fresher
    live one.

    `apply_storage_interval`: WiCAN honours `storage_interval_seconds`;
    `store_torque_telemetry` never checked it. Torque therefore passes False to
    preserve today's behavior. That Torque ignores storage intervals is a
    pre-existing bug, deliberately NOT fixed here (see Follow-ups).
    """

    latest: str = "always"  # 'always' | 'if_newer'
    apply_storage_interval: bool = True
    sync_odometer: bool = False
    observe_movement: bool = False


@dataclass
class IngestBatch:
    """The normalized result of parsing one message or request."""

    device_key: str
    readings: list[Reading] = field(default_factory=list)
    #: 'online' | 'offline' | None. None means LEAVE UNCHANGED, and is the
    #: default for a reason: `update_device_status` treats None as "keep the
    #: current value" while still refreshing `last_seen`
    #: (`livelink_service.py:575`). Defaulting a telemetry batch to "online"
    #: would let a RETAINED message replayed after a gateway's LWT offline mark
    #: the dead gateway alive again. Only an explicit status signal sets this.
    device_status: DeviceStatusType | None = None
    ecu_status: ECUStatusType | None = None
    session: SessionSignal | None = None
    dtcs: list[str] = field(default_factory=list)
    location: GeoPoint | None = None
    #: Naive UTC. None means "use server time".
    timestamp: datetime | None = None
    #: Written to livelink_devices.battery_voltage, not just stored as telemetry.
    battery_voltage: float | None = None
    #: Whether this batch means "the WiFi came back". True only for message
    #: types that do it today: WiCAN `can/rx`, not WiCAN `battery`. Verified:
    #: `_handle_battery` (mqtt_subscriber.py:366-401) contains zero calls to
    #: `clear_pending_offline`, so a battery frame must NOT cancel a pending
    #: offline or a brief WiFi drop stops splitting drives the way it does now.
    clear_pending_offline: bool = False
    #: Whether stored values are checked against warning thresholds. Verified
    #: against today's behavior: WiCAN `can/rx` DOES (mqtt_subscriber.py:470),
    #: WiCAN `battery` does NOT, Torque does NOT (zero calls in routes/torque.py).
    #: Defaulting this True would start sending notifications that have never
    #: fired. generic_mqtt sets it True deliberately: low-tank alerting is a
    #: feature of this project, not a regression.
    alert_on_thresholds: bool = False
    #: Whether an UNLINKED device (vin IS NULL) should be ignored entirely.
    #: The three WiCAN handlers genuinely differ here and the difference is
    #: user-visible, so it cannot be a blanket rule:
    #:   can/rx  returns at `if not device.vin` BEFORE any status update
    #:           (mqtt_subscriber.py:419-423)        -> requires_link=True
    #:   status  calls update_device_status OUTSIDE its `if device.vin` block
    #:           (mqtt_subscriber.py:357)            -> requires_link=False
    #:   battery calls update_device_status BEFORE its `if device.vin`
    #:           (mqtt_subscriber.py:385)            -> requires_link=False
    #: Getting this wrong breaks the discover-then-link flow: a freshly
    #: auto-discovered device would never appear online in the admin UI.
    #: Defaults True so a NEW module is inert until deliberately linked.
    requires_link: bool = True


class BaseSourceModule(ABC):
    """One telemetry source."""

    kind: ClassVar[str]
    capabilities: ClassVar[frozenset[Capability]]
    storage_policy: ClassVar[StoragePolicy] = StoragePolicy()

    async def subscriptions(self, db: AsyncSession) -> list[str]:
        """Exact MQTT topics this module wants. HTTP-only sources return [].

        Async and database-aware so `generic_mqtt` can return topics from its
        mapping table, which is what makes a UI-added row change what the
        broker sends us.
        """
        return []

    async def resolve_device(self, db: AsyncSession, device_key: str) -> LiveLinkDevice | None:
        """Find the device a batch belongs to.

        The one deliberately impure hook: device resolution is inherently
        database work, so it lives here rather than contaminating `parse`.

        Default is lookup by `device_id`, auto-discovering only when the module
        declares AUTO_DISCOVER. Torque overrides it because its `device_key` is
        a path token, not a device id.
        """
        from app.services.livelink_service import LiveLinkService

        svc = LiveLinkService(db)
        device = await svc.get_device_by_id(device_key)
        if device is None and Capability.AUTO_DISCOVER in self.capabilities:
            device, _ = await svc.auto_discover_device(device_key)
        return device

    @abstractmethod
    async def parse(self, env: Envelope) -> IngestBatch | None:
        """Wire format to normalized batch. None means "not mine, ignore"."""

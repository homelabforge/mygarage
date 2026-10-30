"""The contract every LiveLink telemetry source implements.

A module is a PURE parser: wire format in, normalized `IngestBatch` out. It
performs no database work and has no side effects, which is what makes each
one testable against a payload fixture alone. All orchestration (device
resolution, session handling, storage, alerting) belongs to
`app.services.livelink_ingest`.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.livelink import DeviceStatusType, ECUStatusType
from app.schemas.livelink_ingest import WiCANPayload
from app.utils.logging_utils import sanitize_for_log

if TYPE_CHECKING:
    from app.models.livelink_device import LiveLinkDevice

logger = logging.getLogger(__name__)

#: (kind, device id) pairs already warned about, this process: a topic map
#: naming the wrong device would otherwise log on every message.
_FOREIGN_WARNED: set[tuple[str, str]] = set()


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
    #: The broker's retain flag: a replay of the last value it holds, of
    #: unknown age, not something the device just said. `ingest` drops it
    #: unless it is a status topic's own `offline` (an LWT).
    retain: bool = False


@dataclass(frozen=True)
class HttpEnvelope:
    """One HTTP ingest request."""

    token: str
    params: Mapping[str, str]


@dataclass(frozen=True)
class WicanHttpsEnvelope:
    """One WiCAN HTTPS POST, already validated.

    The route keeps the token check, and for a telemetry-only POST the token
    is the only thing naming the device, so it hands the id over resolved.
    """

    device_id: str
    payload: WiCANPayload


Envelope = MqttEnvelope | HttpEnvelope | WicanHttpsEnvelope


@dataclass(frozen=True)
class WireUnit:
    """A unit and class a device declared for one key (R12)."""

    unit: str | None
    param_class: str | None = None


@dataclass(frozen=True)
class DiscoveryInfo:
    """What a device says about itself, for discovery and the device card."""

    hw_version: str | None = None
    fw_version: str | None = None
    git_version: str | None = None
    sta_ip: str | None = None


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

    These three fields are not preferences. Each one started as a real,
    pre-existing behavioral difference between the WiCAN and Torque paths,
    made explicit so the port could not silently merge them:

    `latest`: WiCAN's 'always' overwrites vehicle_telemetry_latest unless the
    reading is older than the stored one (`_upsert_latest_value`; an equal
    timestamp writes a new value, but an exact duplicate changes nothing);
    Torque's 'if_newer' only when
    strictly newer (`_update_latest_if_newer`), so a backfilled row never
    clobbers a fresher live one.

    `storage_interval_seconds` isn't one of them: it thins the history rows
    for every source. The old Torque writer never checked it, which was a
    bug, fixed in G5b-12.
    """

    latest: str = "always"  # 'always' | 'if_newer'
    sync_odometer: bool = False
    observe_movement: bool = False


@dataclass
class IngestBatch:
    """The normalized result of parsing one message or request."""

    device_key: str
    readings: list[Reading] = field(default_factory=list)
    #: Units a source declares ahead of any value, by param_key. Torque sends
    #: them once per session, in a request with no values.
    declared_units: dict[str, str] = field(default_factory=dict)
    #: 'online' | 'offline' | None. None means LEAVE UNCHANGED and still bumps
    #: `last_seen`; Torque sends it so a phone that only uploads while driving
    #: never enters the offline sweep. It used to keep a retained replay from
    #: reviving a dead gateway too, but R1 drops retained telemetry before
    #: `resolve_device` now, so a live generic_mqtt reading sets 'online'.
    device_status: DeviceStatusType | None = None
    #: True only when `device_status` is a status topic's own value (generic
    #: `role='status'`). WiCAN and a generic reading synthesize `online` from
    #: a message arriving, so they never set it. A retained batch is applied
    #: only when this is set and the status is `offline`.
    status_from_wire: bool = False
    ecu_status: ECUStatusType | None = None
    session: SessionSignal | None = None
    dtcs: list[str] = field(default_factory=list)
    location: GeoPoint | None = None
    #: Naive UTC. None means "use server time".
    timestamp: datetime | None = None
    #: Written to livelink_devices.battery_voltage, not just stored as telemetry.
    battery_voltage: float | None = None
    #: Written to the device row too. None leaves the stored value alone.
    rssi: int | None = None
    sta_ip: str | None = None
    #: Versions for a discovered device, or to refresh an existing one.
    discovery: DiscoveryInfo | None = None
    #: Whether an unknown device may be created from this batch (the module
    #: must also declare AUTO_DISCOVER). Only a WiCAN HTTPS telemetry-only
    #: POST says no: it names its device by token, so it can't be a new one.
    allow_discovery: bool = True
    #: Units the device declared on the wire, by canonical key. Persisted per
    #: device (R12), before the enabled and link checks.
    declared_wire_units: dict[str, WireUnit] = field(default_factory=dict)
    #: True when `declared_wire_units` is the device's WHOLE profile (a WiCAN
    #: boot config), so its stored `wire` keys not in it are dropped. Never
    #: set from a status block alone: the schema defaults `config` to `{}`.
    wire_profile: bool = False
    #: Whether this batch means "the WiFi came back". WiCAN `can/rx` and HTTPS
    #: telemetry say yes, WiCAN `battery` says no: the old `_handle_battery`
    #: never cleared a pending offline, so a battery frame mustn't either, or a
    #: brief WiFi drop stops splitting drives.
    clear_pending_offline: bool = False
    #: Whether stored values are checked against warning thresholds. WiCAN
    #: `can/rx` and HTTPS do; WiCAN `battery` and Torque don't, since neither
    #: old handler called `check_thresholds`. Defaulting this True would start
    #: sending alerts that never fired. generic_mqtt sets it on purpose:
    #: low-tank alerts are the point.
    alert_on_thresholds: bool = False
    #: Whether an UNLINKED device (vin IS NULL) should be ignored entirely.
    #: The old WiCAN MQTT handlers (in mqtt_subscriber.py until e84a798e)
    #: differed here, and it shows in the UI, so it's per batch:
    #:   can/rx  returned at `if not device.vin` before any status update
    #:                                               -> requires_link=True
    #:   status  updated status outside its `if device.vin` block
    #:                                               -> requires_link=False
    #:   battery updated status before its `if device.vin`
    #:                                               -> requires_link=False
    #: Every WiCAN HTTPS batch is False too, so an unlinked one's `last_seen`
    #: stays fresh. Getting this wrong breaks discover-then-link: a freshly
    #: discovered device never shows online in the admin UI. Defaults True so
    #: a NEW module is inert until it's linked.
    requires_link: bool = True


class BaseSourceModule(ABC):
    """One telemetry source."""

    kind: ClassVar[str]
    capabilities: ClassVar[frozenset[Capability]]
    storage_policy: ClassVar[StoragePolicy] = StoragePolicy()
    #: The canonical keys only this source names, from a fixed PID map of its
    #: own (Torque's `TORQUE_ODOMETER` and `KFF...` PIDs). Empty for a source
    #: whose keys the device or its owner names (WiCAN autopids, generic MQTT
    #: topic maps), and never a shared OBD alias like `SPEED`: another kind
    #: sends those too. The registry hands a kind every other module's set, so
    #: a WiCAN's odometer scan can skip a key that was never its (FW-A-r4a).
    #: Migration 133 reads this at run time, so a new entry changes what it
    #: labels on a database that hasn't upgraded yet: that needs a migration
    #: of its own, not just the edit.
    own_param_keys: ClassVar[frozenset[str]] = frozenset()

    async def subscriptions(self, db: AsyncSession) -> list[str]:
        """Exact MQTT topics this module wants. HTTP-only sources return [].

        Async and database-aware so `generic_mqtt` can return topics from its
        mapping table, which is what makes a UI-added row change what the
        broker sends us.
        """
        return []

    async def resolve_device(
        self, db: AsyncSession, batch: IngestBatch
    ) -> tuple[LiveLinkDevice | None, bool]:
        """Find the device a batch belongs to: `(device, discovered)`.

        The one deliberately impure hook: device resolution is inherently
        database work, so it lives here rather than contaminating `parse`.

        Default is lookup by `device_id`, auto-discovering only when the module
        declares AUTO_DISCOVER and the batch allows it. A known device gets its
        versions refreshed from `batch.discovery`, enabled or not. Torque
        overrides it because its `device_key` is a path token, not a device id.

        Only a device of this module's kind comes back (FB-1): the pipeline
        runs the module's capabilities on whatever this returns, so a WiCAN
        upload naming a sensor's id would drive a session on a parked trailer.
        Checked here, before the version refresh writes to the row.
        """
        from app.services.livelink_service import LiveLinkService

        svc = LiveLinkService(db)
        device = await svc.get_device_by_id(batch.device_key)
        if device is not None and not self.owns(device):
            return None, False
        if device is None and not (
            Capability.AUTO_DISCOVER in self.capabilities and batch.allow_discovery
        ):
            return None, False
        if device is not None and batch.discovery is None:
            return device, False
        info = batch.discovery or DiscoveryInfo()
        return await svc.auto_discover_device(
            batch.device_key,
            hw_version=info.hw_version,
            fw_version=info.fw_version,
            git_version=info.git_version,
            sta_ip=info.sta_ip,
        )

    def owns(self, device: LiveLinkDevice) -> bool:
        """Whether ``device`` is this source's to ingest, by kind (FB-1).

        A device of another kind named by this source's batch is refused, and
        said so once per process.
        """
        if device.kind == self.kind:
            return True
        if (self.kind, device.device_id) not in _FOREIGN_WARNED:
            _FOREIGN_WARNED.add((self.kind, device.device_id))
            logger.warning(
                "Ignoring %s data for device %s, which is a %s device",
                self.kind,
                sanitize_for_log(device.device_id),
                sanitize_for_log(device.kind),
            )
        return False

    @abstractmethod
    async def parse(self, env: Envelope) -> IngestBatch | None:
        """Wire format to normalized batch. None means "not mine, ignore"."""

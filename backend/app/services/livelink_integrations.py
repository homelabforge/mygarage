"""Status rules for the LiveLink integrations card.

Pure functions. No database, no broker, no clock of their own: `now` and the
timeout are injected so every rule is testable without sleeping, and so the
card's four dots cannot drift into four different nested ternaries in JSX the
way the single dot they replace did.

`status` is one of 'ok' | 'attention' | 'off'. `reason` says why, because the
status and the counts together cannot distinguish an unlinked device from a
linked one that has never reported: both are 'attention' with zero online.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.livelink_device import LiveLinkDevice
    from app.schemas.livelink import DeviceFirmwareStatus


@dataclass(frozen=True)
class TabStatus:
    """One tab's state and the reason for it."""

    status: str
    reason: str


_OK = TabStatus("ok", "receiving")
_DISABLED = TabStatus("off", "disabled")
_NOT_CONFIGURED = TabStatus("off", "not_configured")
_NOT_LINKED = TabStatus("attention", "not_linked")
_NO_DATA = TabStatus("attention", "no_data")
_FIRMWARE = TabStatus("attention", "firmware_update")
_BROKER_DOWN = TabStatus("attention", "broker_down")


def device_is_linked(device: LiveLinkDevice) -> bool:
    """A device with no vin is not finished being set up.

    This is not a corner case. A WiCAN auto-discovers itself and its
    `can/status` handler sets `device_status='online'` with
    `requires_link=False`, while the `can/rx` handler carrying the actual
    telemetry is `requires_link=True` and is dropped by
    `livelink_ingest.ingest`. So a freshly plugged-in dongle sits at
    `device_status='online', vin=NULL` indefinitely, storing nothing.
    """
    return device.vin is not None


def device_is_online(device: LiveLinkDevice, offline_timeout_minutes: int, now: datetime) -> bool:
    """Whether a device is currently reporting.

    Not simply `device_status == 'online'`, for two reasons:

    - Torque never sets `device_status`, so it stays 'unknown' while
      `last_seen` moves on every upload; 'unknown' falls back to `last_seen`.
      A generic sensor with no status topic used to sit there too, until a
      live reading started marking it online (D5a).
    - A disabled device freezes at its last status, because `ingest` returns
      before the status update and the offline sweep ignores `enabled`. Hence
      the `enabled` conjunct rather than trusting the stored value.
    """
    if not device.enabled:
        return False
    if device.device_status == "online":
        return True
    if device.device_status != "unknown" or device.last_seen is None:
        return False

    last_seen = device.last_seen
    if last_seen.tzinfo is None and now.tzinfo is not None:
        last_seen = last_seen.replace(tzinfo=now.tzinfo)
    return last_seen >= now - timedelta(minutes=offline_timeout_minutes)


def firmware_is_pending(status: DeviceFirmwareStatus | None) -> bool:
    """An update the operator has not already dismissed.

    `FirmwareService.check_device_firmware` reports `update_available` as a
    bare version comparison and returns `skipped_version` separately, so the
    carve-out belongs to every caller. Without it, skipping a release leaves a
    permanently yellow dot, which trains the operator to ignore the colour.
    """
    if status is None or not status.update_available:
        return False
    return status.latest_version != status.skipped_version


def derive_group_status(
    devices: Sequence[LiveLinkDevice],
    firmware_by_id: Mapping[str, DeviceFirmwareStatus],
    offline_timeout_minutes: int,
    now: datetime,
    *,
    livelink_enabled: bool,
) -> TabStatus:
    """Status for a tab backed by one or more devices.

    Order matters: setup problems outrank a firmware update, because an
    unlinked device needs linking before an update is worth mentioning.
    """
    if not livelink_enabled:
        return _DISABLED
    if not devices:
        return _NOT_CONFIGURED

    active = [d for d in devices if d.enabled]
    if not active:
        return _DISABLED

    linked = [d for d in active if device_is_linked(d)]
    if not linked:
        return _NOT_LINKED

    if not any(device_is_online(d, offline_timeout_minutes, now) for d in linked):
        return _NO_DATA

    if any(firmware_is_pending(firmware_by_id.get(d.device_id)) for d in active):
        return _FIRMWARE

    return _OK


def derive_broker_status(connection_status: str, *, livelink_enabled: bool) -> TabStatus:
    """Status for the broker tab.

    'disconnected', 'connecting', 'error' and anything unrecognised all mean
    'not currently healthy'. Failing safe matters here: a state this code has
    never heard of must never read as fine.
    """
    if not livelink_enabled or connection_status == "disabled":
        return _DISABLED
    if connection_status == "connected":
        return _OK
    return _BROKER_DOWN

"""The single orchestration path for every LiveLink telemetry source.

Before this module there were two: `mqtt_subscriber._handle_telemetry` and
`routes/torque._ingest`, each re-implementing device resolution, session
semantics, status updates and storage. That duplication is why adding a third
source meant adding a third copy.

Capabilities are consulted before any side effect, so a module that does not
declare DRIVE_SESSION has no reachable path to SessionService at all.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.livelink_device import LiveLinkDevice
from app.models.vehicle import Vehicle
from app.services import declared_units
from app.services.device_units import DeviceUnitService
from app.services.dtc_service import DTCService
from app.services.livelink_service import LiveLinkService
from app.services.livelink_sources.base import (
    BaseSourceModule,
    Capability,
    Envelope,
    InferSession,
    IngestBatch,
    MqttEnvelope,
    SessionSignal,
    StatusTransition,
)
from app.services.location_service import LocationService
from app.services.notifications.dispatcher import NotificationDispatcher
from app.services.session_service import SessionService
from app.services.telemetry_service import TelemetryService
from app.utils.datetime_utils import utc_now
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

#: Why `ingest` stopped short. None on an `IngestOutcome` means it ran through.
DropReason = Literal[
    "livelink_disabled",  # the master switch is off
    "ignored",  # the module's parser said "not mine"
    "retained",  # a broker replay (R1)
    "unknown_device",  # no such device, and none was discovered
    "device_disabled",  # the device's own switch is off (A-4)
    "unlinked",  # no vehicle, so no telemetry
]


@dataclass
class IngestOutcome:
    """What `ingest` did, for a caller with a response to build (HTTPS).

    MQTT ignores it.
    """

    device: LiveLinkDevice | None = None
    discovered: bool = False
    stored_count: int = 0
    dtc_count: int = 0
    reason: DropReason | None = None


async def apply_session_signal(
    db: AsyncSession,
    device: LiveLinkDevice,
    signal: SessionSignal,
    timestamp: datetime | None = None,
) -> DriveSession | None:
    """Translate a source's session intent into SessionService calls.

    Returns the resolved session when the source supplies one (Torque needs
    `session.id` for its location breadcrumbs); None otherwise.

    MUST be called before `update_device_status`: every transition below reads
    the device's CURRENT `ecu_status` to detect a change.
    """
    if device.vin is None:
        return None
    livelink = LiveLinkService(db)
    sessions = SessionService(db)

    if isinstance(signal, InferSession):
        # Data arriving at all means the ECU is on. Mirrors mqtt_subscriber.py:435-443.
        if device.pending_offline_at:
            await livelink.clear_pending_offline(device.device_id)
        if device.ecu_status != "online":
            await sessions.handle_ecu_online(device.vin, device.device_id)
        return None

    if isinstance(signal, StatusTransition):
        # Mirrors mqtt_subscriber.py:303-362, grace period included.
        if signal.ecu_status == "unknown":
            return None
        if signal.ecu_status == "online":
            if device.pending_offline_at:
                await livelink.clear_pending_offline(device.device_id)
            else:
                await sessions.handle_ecu_online(device.vin, device.device_id)
            return None
        grace = await livelink.get_session_grace_period_seconds()
        if grace > 0:
            await livelink.set_pending_offline(device.device_id)
        else:
            await sessions.handle_ecu_offline(device.vin, device.device_id)
        return None

    # ExplicitSession is the only remaining member of the SessionSignal union;
    # both branches above return, so an isinstance check here is provably
    # always true and pyright rejects it (reportUnnecessaryIsInstance).
    return await sessions.resolve_torque_session(device, signal.external_id, timestamp or utc_now())


async def _apply_retained_offline(batch: IngestBatch, db: AsyncSession) -> None:
    """A retained LWT `offline`: set the status on a known device, nothing else.

    No discovery (a replay is no reason to create a device), no `last_seen`
    bump, and no more than the same message would do live: a disabled device
    freezes at its last status, and an unlinked one is skipped when the batch
    requires a link.
    """
    livelink = LiveLinkService(db)
    device = await livelink.get_device_by_id(batch.device_key)
    if device is None or not device.enabled:
        return
    if batch.requires_link and not device.vin:
        return
    await livelink.update_device_status(
        device_id=device.device_id, device_status="offline", touch_last_seen=False
    )


async def ingest(module: BaseSourceModule, env: Envelope, db: AsyncSession) -> IngestOutcome:
    """Parse one message or request and apply it. Does NOT commit."""
    # The master switch ("Enable LiveLink"). Every MQTT message, every Torque
    # upload and every WiCAN HTTPS POST comes through here; the periodic jobs
    # check it themselves, and SD backfill in SdBackfillService.backfill_device.
    # Checked before parsing, so a switched-off install also discovers no new
    # device and bumps no last_seen, which is what the integrations card's
    # all-off state tells the operator.
    if not await LiveLinkService(db).is_enabled():
        return IngestOutcome(reason="livelink_disabled")

    batch = await module.parse(env)
    if batch is None:
        return IngestOutcome(reason="ignored")

    # A retained message is the broker's last copy, of unknown age, and both
    # live sources republish within seconds anyway. Only a status topic's own
    # `offline` (an LWT) is worth applying; a retained `online` is dropped too,
    # since a gateway that died without an LWT leaves exactly that behind (R1).
    if isinstance(env, MqttEnvelope) and env.retain:
        if batch.status_from_wire and batch.device_status == "offline":
            await _apply_retained_offline(batch, db)
        return IngestOutcome(reason="retained")

    device, discovered = await module.resolve_device(db, batch)
    if device is None:
        return IngestOutcome(reason="unknown_device")
    outcome = IngestOutcome(device=device, discovered=discovered)

    # D4a. The dispatcher checks the General drawer's switch itself.
    if discovered:
        await NotificationDispatcher(db).notify_livelink_new_device(
            device.device_id, batch.discovery.hw_version if batch.discovery else None
        )

    # Before the enabled and link checks (R12): a WiCAN declares its units
    # only on the first POST after a boot, a new device is still unlinked
    # then, and a disabled one that reboots would lose them until the next
    # boot. Declarations are device metadata, not telemetry.
    if batch.declared_wire_units:
        await DeviceUnitService(db).record(
            device, batch.declared_wire_units, whole_profile=batch.wire_profile
        )

    if not device.enabled:
        outcome.reason = "device_disabled"
        return outcome
    if batch.requires_link and not device.vin:
        outcome.reason = "unlinked"
        return outcome

    livelink = LiveLinkService(db)
    timestamp = batch.timestamp or utc_now()

    # Only batches that mean "the WiFi came back" cancel a pending offline.
    # A WiCAN battery frame must NOT, or a brief drop stops splitting drives
    # the way it does today (_handle_battery has zero clear_pending_offline calls).
    if batch.clear_pending_offline and device.pending_offline_at:
        await livelink.clear_pending_offline(device.device_id)

    session: DriveSession | None = None
    if device.vin and Capability.DRIVE_SESSION in module.capabilities and batch.session is not None:
        session = await apply_session_signal(db, device, batch.session, timestamp)

    # AFTER the session signal: the detector above reads the old ecu_status.
    # None means LEAVE UNCHANGED and still bumps last_seen
    # (`device_status or LiveLinkDevice.device_status`). Never default this to
    # "online": a telemetry topic says nothing about the gateway's status.
    battery = batch.battery_voltage
    await livelink.update_device_status(
        device_id=device.device_id,
        device_status=batch.device_status,
        ecu_status=batch.ecu_status,
        # Same rule as the readings below: a NaN is not a voltage.
        battery_voltage=battery if battery is not None and math.isfinite(battery) else None,
        rssi=batch.rssi,
        sta_ip=batch.sta_ip,
    )

    if not device.vin:
        outcome.reason = "unlinked"  # discovered but unlinked: status only, never telemetry
        return outcome

    # Torque declares its units in a request of their own, before any value.
    # Held for this device until a value arrives; rows on file get them now.
    if batch.declared_units:
        declared_units.remember(device.device_id, batch.declared_units)
        await TelemetryService(db).fill_declared_units(batch.declared_units)

    # NaN and infinity never reach storage, whatever the source's parser let
    # through: a NaN binds as NULL and the latest table is NOT NULL on SQLite.
    finite = [r for r in batch.readings if math.isfinite(r.value)]
    if len(finite) < len(batch.readings):
        logger.debug(
            "Dropped %d non-finite readings from %s device %s",
            len(batch.readings) - len(finite),
            sanitize_for_log(module.kind),
            sanitize_for_log(device.device_id),
        )

    if finite:
        telemetry = TelemetryService(db)
        readings = [
            r if r.unit else replace(r, unit=declared_units.unit_for(device.device_id, r.param_key))
            for r in finite
        ]
        # The device's stored declarations fill what's still missing, and mph
        # becomes km/h here, once, whichever way the unit arrived (R4, R12).
        readings = await DeviceUnitService(db).resolve_readings(device.device_id, readings)
        result = await telemetry.store_readings(
            vin=device.vin,
            device_id=device.device_id,
            readings=readings,
            timestamp=timestamp,
            policy=module.storage_policy,
            # Task 17 reads `device.odometer_param_key` from this to decide
            # whether to normalise and record an odometer reading.
            #
            # GATED on the capability, deliberately. Passing it unconditionally
            # would let ANY source with a declared key write odometer records,
            # which falsifies the central claim in `Capability`'s docstring that
            # a module without a capability has no reachable path to its
            # machinery. A `generic_mqtt` device whose owner picks an odometer
            # parameter in Settings must still record nothing until that module
            # is deliberately granted ODOMETER.
            device=device if Capability.ODOMETER in module.capabilities else None,
        )
        outcome.stored_count = result.stored_count
        # Gated: WiCAN can/rx alerts today, WiCAN battery and Torque do NOT.
        # Ungated, this port would start sending notifications that have never
        # fired for a Torque user or on a battery frame.
        if batch.alert_on_thresholds:
            # A preset sensor (a propane tank) sits past its line for days, so
            # its readings notify once per crossing rather than every cooldown.
            once = device.preset_key is not None
            # Gated like the odometer step it stands for: only a module with
            # ODOMETER normalises one, so a generic_mqtt ODOMETER is raw (D2a).
            odometer_normalised = Capability.ODOMETER in module.capabilities
            for param_key, value in result.validated_data.items():
                if isinstance(value, (int, float)):
                    await telemetry.check_thresholds(
                        device.vin,
                        param_key,
                        float(value),
                        once=once,
                        odometer_normalised=odometer_normalised,
                        declared_odometer_key=device.odometer_param_key,
                    )

    # Gated like every other side effect: only a module that declares DTC can
    # write codes, whatever its batch carries.
    if Capability.DTC in module.capabilities and batch.dtcs and device.vin:
        await DTCService(db).process_dtcs(device.vin, device.device_id, batch.dtcs)
        outcome.dtc_count = len(batch.dtcs)

    if Capability.LOCATION in module.capabilities and batch.location is not None:
        vehicle = (
            await db.execute(select(Vehicle).where(Vehicle.vin == device.vin))
        ).scalar_one_or_none()
        if vehicle and vehicle.location_tracking_enabled:
            await LocationService(db).record_point(
                vin=device.vin,
                device_id=device.device_id,
                drive_session_id=session.id if session else None,
                timestamp=timestamp,
                latitude=batch.location.latitude,
                longitude=batch.location.longitude,
                speed=batch.location.speed,
                heading=batch.location.heading,
                altitude=batch.location.altitude,
            )

    logger.debug(
        "Ingested %d readings from %s device %s",
        len(batch.readings),
        sanitize_for_log(module.kind),
        sanitize_for_log(device.device_id),
    )
    return outcome

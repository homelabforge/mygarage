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
from dataclasses import replace
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.drive_session import DriveSession
from app.models.livelink_device import LiveLinkDevice
from app.models.vehicle import Vehicle
from app.services import declared_units
from app.services.livelink_service import LiveLinkService
from app.services.livelink_sources.base import (
    BaseSourceModule,
    Capability,
    Envelope,
    InferSession,
    SessionSignal,
    StatusTransition,
)
from app.services.location_service import LocationService
from app.services.session_service import SessionService
from app.services.telemetry_service import TelemetryService
from app.utils.datetime_utils import utc_now
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


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


async def ingest(module: BaseSourceModule, env: Envelope, db: AsyncSession) -> None:
    """Parse one message or request and apply it. Does NOT commit."""
    # The master switch ("Enable LiveLink"). Every MQTT message and every Torque
    # upload comes through here; the HTTPS route and the periodic jobs check it
    # themselves, and SD backfill in SdBackfillService.backfill_device. Checked
    # before parsing, so a switched-off install also discovers no new device
    # and bumps no last_seen, which is what the integrations card's all-off
    # state tells the operator.
    if not await LiveLinkService(db).is_enabled():
        return

    batch = await module.parse(env)
    if batch is None:
        return

    device = await module.resolve_device(db, batch.device_key)
    if device is None or not device.enabled:
        return
    if batch.requires_link and not device.vin:
        return

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
    # (`livelink_service.py:575`: `device_status or LiveLinkDevice.device_status`).
    # Never default this to "online", or a retained message replayed after a
    # gateway's LWT offline resurrects the dead gateway.
    await livelink.update_device_status(
        device_id=device.device_id,
        device_status=batch.device_status,
        ecu_status=batch.ecu_status,
        battery_voltage=batch.battery_voltage,
    )

    if not device.vin:
        return  # discovered but unlinked: status only, never telemetry

    # Torque declares its units in a request of their own, before any value.
    # Held for this device until a value arrives; rows on file get them now.
    if batch.declared_units:
        declared_units.remember(device.device_id, batch.declared_units)
        await TelemetryService(db).fill_declared_units(batch.declared_units)

    if batch.readings:
        telemetry = TelemetryService(db)
        readings = [
            r if r.unit else replace(r, unit=declared_units.unit_for(device.device_id, r.param_key))
            for r in batch.readings
        ]
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
        # Gated: WiCAN can/rx alerts today, WiCAN battery and Torque do NOT.
        # Ungated, this port would start sending notifications that have never
        # fired for a Torque user or on a battery frame.
        if batch.alert_on_thresholds:
            # A preset sensor (a propane tank) sits past its line for days, so
            # its readings notify once per crossing rather than every cooldown.
            once = device.preset_key is not None
            for param_key, value in result.validated_data.items():
                if isinstance(value, (int, float)):
                    await telemetry.check_thresholds(device.vin, param_key, float(value), once=once)

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

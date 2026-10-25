"""The Torque Pro Android app, over HTTP GET/POST.

Extracted verbatim in behavior from `routes/torque.py:_ingest`.

Declares ODOMETER as a CAPABILITY but leaves `sync_odometer` False. Torque
historically recorded no odometer at all: the old Torque writer never called
`_sync_odometer_from_telemetry`, and a Torque device records no key by name:
its `TORQUE_ODOMETER` would match WiCAN's `ODOMETER_NAME_PATTERNS` scan, but
that scan is WiCAN's alone (`is_recorded_odometer_key`), and it skips
Torque's own keys (`own_param_keys`, FW-A-r4a), so on a car with both the
WiCAN never reads the phone's total as its own. Flipping the storage policy
would have started syncing for every Torque user AND replaced the newer-only
latest write. Instead the capability opens the door and each DEVICE decides
by naming its own `odometer_param_key`; a device that names nothing behaves
exactly as before.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.services.livelink_sources.base import (
    BaseSourceModule,
    Capability,
    ExplicitSession,
    GeoPoint,
    HttpEnvelope,
    IngestBatch,
    Reading,
    StoragePolicy,
)
from app.services.torque_pid_map import (
    TORQUE_DEFAULT_UNITS,
    TORQUE_OWN_KEYS,
    TORQUE_PID_NAMES,
    parse_torque_query,
)

logger = logging.getLogger(__name__)


def _to_decimal(value: float | None) -> Decimal | None:
    """Optional float to Decimal for the location_points Numeric columns."""
    return Decimal(str(value)) if value is not None else None


class TorqueModule(BaseSourceModule):
    """Torque Pro."""

    kind = "torque"
    capabilities = frozenset(
        {
            Capability.TELEMETRY,
            Capability.DRIVE_SESSION,
            Capability.LOCATION,
            # Capability only. storage_policy.sync_odometer stays False: that
            # flag routes storage through store_telemetry and would replace
            # Torque's newer-only latest write with an unconditional one.
            # Whether an odometer is actually recorded is the DEVICE's call,
            # via odometer_param_key.
            Capability.ODOMETER,
        }
    )
    #: Exactly what the old Torque writer did: newer-only latest updates so a
    #: backfilled row never clobbers a fresher live one, and no storage-interval
    #: check because it never performed one.
    storage_policy = StoragePolicy(
        latest="if_newer",
        apply_storage_interval=False,
        sync_odometer=False,
        observe_movement=False,
    )
    #: Its extended PIDs are Torque's alone; the standard ones are shared aliases.
    own_param_keys = TORQUE_OWN_KEYS

    async def resolve_device(
        self, db: AsyncSession, batch: IngestBatch
    ) -> tuple[LiveLinkDevice | None, bool]:
        """Torque's device_key is a path token, not a device id. Never discovers."""
        from app.services.torque_service import TorqueService

        return await TorqueService(db).resolve_by_token(batch.device_key), False

    async def parse(self, env) -> IngestBatch | None:
        if not isinstance(env, HttpEnvelope):
            return None

        reading = parse_torque_query(env.params)
        now = datetime.now(UTC).replace(tzinfo=None)
        ts = now
        if reading.time_ms:
            try:
                candidate = datetime.fromtimestamp(reading.time_ms / 1000, tz=UTC).replace(
                    tzinfo=None
                )
            except OverflowError, OSError, ValueError:
                # `time_ms` is only digit-validated, never range-checked. Degrade
                # to server-now rather than 500ing: Torque retries on any non-OK
                # response, so a bad device clock would wedge in a retry loop.
                candidate = now
            # Trust a PAST device clock (legitimate replay/backfill) but never a
            # future one: a future started_at finalizes to a NEGATIVE duration
            # and poisons ordering and dedup (R2-H2).
            ts = min(candidate, now)

        location = None
        lat, lon = reading.gps.get("latitude"), reading.gps.get("longitude")
        if lat is not None and lon is not None:
            location = GeoPoint(
                latitude=Decimal(str(lat)),
                longitude=Decimal(str(lon)),
                speed=_to_decimal(reading.gps.get("speed")),
                heading=_to_decimal(reading.gps.get("heading")),
                altitude=_to_decimal(reading.gps.get("altitude")),
            )

        return IngestBatch(
            device_key=env.token,
            readings=[
                Reading(
                    key,
                    float(value),
                    unit=TORQUE_DEFAULT_UNITS.get(key),
                    display_name=TORQUE_PID_NAMES.get(key),
                )
                for key, value in reading.obd.items()
            ],
            declared_units=reading.default_units,
            # `_ingest` returns OK! and does nothing at all for an unlinked
            # device, so Torque never touched status for one.
            requires_link=True,
            # Torque has no pending-offline concept and never sent threshold
            # alerts (the route had no check_thresholds call before the pipeline).
            clear_pending_offline=False,
            alert_on_thresholds=False,
            # Data arriving means the engine's on. Ending a stale trip doesn't
            # touch ecu_status any more, so this just records it.
            ecu_status="online" if (reading.obd or reading.gps) else None,
            # None: LEAVE device_status as it is (the route never wrote it, so a
            # Torque source stays 'unknown'). "online" here would enrol every
            # phone in check_device_offline_status, which sweeps only devices
            # whose device_status is 'online' and notifies for each one it
            # marks offline: a "device offline" alert after every drive. The
            # integrations card still sees a recent upload as online, via
            # last_seen (livelink_integrations.device_is_online).
            device_status=None,
            session=ExplicitSession(external_id=reading.session),
            location=location,
            timestamp=ts,
        )

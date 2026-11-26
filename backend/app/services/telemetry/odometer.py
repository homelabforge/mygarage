"""Odometer half of TelemetryService: units, sanitizing and the daily record."""

import logging
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import aliased

from app.models import OdometerRecord
from app.models.drive_session import DriveSession
from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_parameter import LiveLinkParameter
from app.models.livelink_topic_map import LiveLinkTopicMap
from app.models.vehicle_telemetry import VehicleTelemetry, VehicleTelemetryLatest
from app.services.device_units import DeviceUnitService, relabel_parameter
from app.services.livelink_sources.base import StoragePolicy
from app.services.telemetry.base import TelemetryBase
from app.services.telemetry.helpers import _delegates_to_store_telemetry
from app.utils.datetime_utils import utc_now
from app.utils.household_time import household_today
from app.utils.odometer_units import (
    ODOMETER_UNIT_KM,
    WICAN_DEVICE_KIND,
    is_converted_odometer_key,
    is_miles_odometer_key,
    is_miles_unit,
    odometer_value_to_km,
    stores_odometer_key_raw,
)

logger = logging.getLogger(__name__)

#: VIN -> date of the last "declared odometer never records" warning. Bounded by
#: the number of vehicles, which is a household's worth, so it never needs
#: eviction.
_DECLARED_ODOMETER_WARNED: dict[str, date] = {}


def normalises_odometer(policy: StoragePolicy, device: LiveLinkDevice | None) -> bool:
    """Whether `store_readings` converts a batch's odometer to km.

    `device` is what the caller passes `store_readings` (None without the
    ODOMETER capability). `store_telemetry` converts every odometer key by the
    device's match (its declared key, else name matching); the simple path
    only a declared one. Torque has ODOMETER and still converts nothing
    without a declared key, so the capability alone doesn't say. `ODOMETER_MI`
    is converted on every path, and `check_thresholds` knows that per key.
    """
    if _delegates_to_store_telemetry(policy):
        return True
    return device is not None and bool(device.odometer_param_key)


class TelemetryOdometerMixin(TelemetryBase):
    """Odometer keys, unit normalisation, sanity checks and the LiveLink record."""

    def _is_odometer_param(self, param_key: str, declared: str | None = None) -> bool:
        """Check if a parameter key represents an odometer reading.

        ``declared`` is the device's ``odometer_param_key``. When set it
        REPLACES the pattern scan for that one key, so a device can name a
        parameter no pattern would match (a vendor custom PID, say) without
        widening the match for anything else. The scan is
        `is_converted_odometer_key`'s, shared with the old-reading guard.
        """
        return is_converted_odometer_key(param_key, declared)

    async def _declared_odometer_key(self, device_id: str) -> str | None:
        """The device's `odometer_param_key`, or None when it declares nothing.

        NULL is the default and the reason existing installs are unaffected:
        every predicate falls back to its usual name matching.
        """
        row = await self.db.execute(
            select(LiveLinkDevice.odometer_param_key).where(LiveLinkDevice.device_id == device_id)
        )
        return row.scalar_one_or_none()

    async def _odometer_units_for(self, device_id: str) -> tuple[str | None, str | None]:
        """Return the device's declared `(odometer_unit, kind)`, or `(None, None)`."""
        row = (
            await self.db.execute(
                select(LiveLinkDevice.odometer_unit, LiveLinkDevice.kind).where(
                    LiveLinkDevice.device_id == device_id
                )
            )
        ).first()
        return row if row else (None, None)

    def _normalised_odometer_keys(
        self, keys: Iterable[str], declared: str | None, *, by_name: bool
    ) -> set[str]:
        """The keys a storage path converts to km.

        `by_name`: `store_telemetry` converts every odometer key by the
        device's match (`declared` replaces the name scan); the simple path
        only a declared one. `ODOMETER_MI` is miles for every kind, so it's
        converted on both (Codex R1-M1).
        """
        return {
            k
            for k in keys
            if is_miles_odometer_key(k)
            or ((by_name or declared) and self._is_odometer_param(k, declared))
        }

    async def _normalize_odometer_units(
        self,
        device_id: str,
        autopid_data: dict[str, float | int | str | None],
        keys: set[str],
        key_units: Mapping[str, str | None] | None = None,
    ) -> dict[str, float | int | str | None]:
        """Return ``autopid_data`` with each odometer in ``keys`` converted to km.

        ``key_units`` is each key's unit as it arrived (this request's
        `config`). It goes through R12's resolution with the device's stored
        rows, so a kept `legacy` row and a boot declaration both reach this.
        `resolve_odometer_unit` has the order: device unit, then that, then
        the key shape (WiCAN only).
        """
        # Values narrowed here, so the loop below needs no None check.
        odometers = {k: v for k, v in autopid_data.items() if v is not None and k in keys}
        if not odometers:
            return autopid_data

        device_unit, device_kind = await self._odometer_units_for(device_id)
        given = key_units or {}
        units = await DeviceUnitService(self.db).resolve_key_units(
            device_id, {k: given.get(k) for k in odometers}
        )

        normalized = dict(autopid_data)
        for param_key, value in odometers.items():
            try:
                converted = odometer_value_to_km(
                    float(value), param_key, device_unit, device_kind, units.get(param_key)
                )
            except TypeError, ValueError:
                continue
            if converted is not None:
                normalized[param_key] = converted
        return normalized

    async def _label_odometer_km(self, param: LiveLinkParameter | None) -> None:
        """A normalised odometer's row says km, whatever an older version wrote (FB-5).

        R4 relabels an mph row the same way. An empty unit gets km too: the
        browser reads an odometer's unit from this row, not its name
        (FW-A-r3). The lines stay: they were always compared with the stored
        values, which were km.

        Rows are global by key, so a key another device stores raw (another
        kind that doesn't declare it, or a WiCAN that declares a different
        key) keeps its label, as migration 133 leaves it (FW-A-r4b). That
        check is a query, so it only runs while the row still needs relabelling.
        """
        if param is None:
            return
        unlabelled = not (param.unit or "").strip()
        if not (unlabelled or is_miles_unit(param.unit)):
            return
        if await self._another_device_stores_raw(param.param_key):
            return
        relabel_parameter(param, ODOMETER_UNIT_KM)

    async def _another_device_stores_raw(self, param_key: str) -> bool:
        """Whether a device that doesn't convert ``param_key`` may have sent it.

        Migration 133's guard for its km stamp, asked live. Every device that
        may have sent the key, judged by `stores_odometer_key_raw`. Raw rows
        alone aren't enough (wave A re-review T2): they prune at 90 days, and a
        deleted device's stay behind under an id that's no longer on file. So
        the evidence is, as in 133:

        - a device on file with raw rows under the key;
        - a device on file with a topic map that sends it the key (generic
          MQTT: that's where its keys come from, and it doesn't prune);
        - a WiCAN on file whose vehicle has a latest row for the key, when it's
          the only device that has reported on that vehicle: linked, or with a
          drive there (a WiCAN names its own autopids, so its vehicle's latest
          rows are the record that outlives the raw ones, but they're the
          vehicle's, not the device's, so with company they prove nothing,
          wave B review M-4);
        - raw rows under the key from a device that's gone. Its kind is
          unknown, so they count as raw, until they prune.

        Torque needs none of these: its keys come from its own fixed map, and
        none of them is an odometer a WiCAN records.
        """
        other = aliased(LiveLinkDevice)
        sent_it = or_(
            exists().where(
                VehicleTelemetry.device_id == LiveLinkDevice.device_id,
                VehicleTelemetry.param_key == param_key,
            ),
            exists().where(
                LiveLinkTopicMap.device_id == LiveLinkDevice.device_id,
                LiveLinkTopicMap.param_key == param_key,
            ),
            and_(
                LiveLinkDevice.kind == WICAN_DEVICE_KIND,
                exists().where(
                    VehicleTelemetryLatest.vin == LiveLinkDevice.vin,
                    VehicleTelemetryLatest.param_key == param_key,
                ),
                ~exists().where(
                    other.vin == LiveLinkDevice.vin, other.device_id != LiveLinkDevice.device_id
                ),
                ~exists().where(
                    DriveSession.vin == LiveLinkDevice.vin,
                    DriveSession.device_id != LiveLinkDevice.device_id,
                ),
            ),
        )
        rows = await self.db.execute(
            select(LiveLinkDevice.kind, LiveLinkDevice.odometer_param_key).where(sent_it)
        )
        if any(stores_odometer_key_raw(param_key, kind, declared) for kind, declared in rows.all()):
            return True
        if not stores_odometer_key_raw(param_key, None):
            return False  # every kind converts it (ODOMETER_MI)
        return await self._a_gone_device_sent(param_key)

    async def _a_gone_device_sent(self, param_key: str) -> bool:
        """Whether a device no longer on file has raw rows under ``param_key``.

        Walks the distinct device ids in the raw table one index seek at a time
        (a handful of devices, ever), the way migration 133 walks a device's keys.
        """
        on_file = set((await self.db.execute(select(LiveLinkDevice.device_id))).scalars().all())
        previous = ""
        while True:
            device_id = await self.db.scalar(
                select(func.min(VehicleTelemetry.device_id)).where(
                    VehicleTelemetry.device_id > previous
                )
            )
            if device_id is None:
                return False
            previous = device_id
            if device_id in on_file:
                continue
            found = await self.db.scalar(
                select(VehicleTelemetry.id)
                .where(
                    VehicleTelemetry.device_id == device_id,
                    VehicleTelemetry.param_key == param_key,
                )
                .limit(1)
            )
            if found is not None:
                return True

    async def _odometer_record_max(self, vin: str) -> float:
        """The vehicle's highest odometer record in km, or 0 with none."""
        found = await self.db.execute(
            select(func.max(OdometerRecord.odometer_km)).where(OdometerRecord.vin == vin)
        )
        return float(found.scalar() or 0)

    async def _sanitize_odometer_value(
        self, vin: str, value: float, *, record_max: float | None = None
    ) -> float | None:
        """Sanitize an odometer value (km), returning None if invalid.

        Applies the same sanity checks as _sync_odometer_from_telemetry:
        - Absolute cap at ~1.6 million km (1M mi equivalent)
        - Reject unreasonable jumps (>16,000 km from existing max)
        - Reject negative/zero values

        ``record_max`` is the vehicle's highest record when the caller already
        has it (an SD pull checks thousands of rows against one).

        Returns:
            Sanitized value if valid, None if should be rejected
        """
        odometer_km = int(round(value))

        # Reject zero/negative
        if odometer_km <= 0:
            return None

        # Absolute cap at ~1.6M km (no vehicle reaches this)
        if odometer_km > 1_600_000:
            logger.warning(
                "Rejected odometer %d km for %s: exceeds 1.6M km cap",
                odometer_km,
                vin[:8],
            )
            return None

        # Max existing odometer_km, to check for unreasonable jumps
        max_odometer_km = (
            record_max if record_max is not None else await self._odometer_record_max(vin)
        )

        # Reject values that are unreasonably higher than existing max
        # (prevents overflow values like 0xFFFFFF from being displayed)
        if max_odometer_km > 0 and odometer_km > float(max_odometer_km) + 16_000:
            logger.warning(
                "Rejected odometer %d km for %s: unreasonable jump from %s",
                odometer_km,
                vin[:8],
                max_odometer_km,
            )
            return None

        return float(odometer_km)

    async def _sync_odometer_from_telemetry(
        self,
        vin: str,
        autopid_data: dict[str, float | int | str | None],
        timestamp: datetime,
        declared: str | None = None,
    ) -> None:
        """Sync odometer record from telemetry if odometer PID is present.

        Keeps at most one LiveLink record per day, to avoid spamming the
        odometer table, marked with source='livelink'. It updates that record
        or creates it beside the day's other readings, and never modifies a
        record of another source.
        """
        # Find odometer value in telemetry
        odometer_value: float | None = None
        odometer_key: str | None = None

        for param_key, value in autopid_data.items():
            if value is None:
                continue

            # Was an inline copy of the pattern scan. It has to go through the
            # predicate, or a device's declaration never reaches this path and a
            # declared key that matches no pattern records nothing, silently.
            if self._is_odometer_param(param_key, declared):
                odometer_value = float(value)
                odometer_key = param_key
                break

        if odometer_value is None or odometer_key is None:
            return  # No odometer PID found

        # Already canonical km: store_telemetry normalised the whole payload
        # through _normalize_odometer_units before any consumer saw it.
        odometer_km = int(round(odometer_value))
        if odometer_km <= 0:
            return  # Invalid odometer reading

        # Sanity check: absolute cap at ~1.6M km (no vehicle reaches this)
        if odometer_km > 1_600_000:
            logger.warning(
                "Rejected odometer %d km for %s: exceeds 1.6M km cap",
                odometer_km,
                vin[:8],
            )
            return

        # Query max existing odometer_km for this VIN to avoid duplicate values
        max_result = await self.db.execute(
            select(func.max(OdometerRecord.odometer_km)).where(OdometerRecord.vin == vin)
        )
        max_odometer_km = max_result.scalar() or 0

        # Sanity check: reject unreasonable jumps (prevents overflow values like 0xFFFFFF)
        if max_odometer_km > 0 and odometer_km > float(max_odometer_km) + 16_000:
            logger.warning(
                "Rejected odometer %d km for %s: unreasonable jump from %s",
                odometer_km,
                vin[:8],
                max_odometer_km,
            )
            return

        # Only proceed if this is a new higher reading.
        # Logged because a units mismatch makes every reading look backwards, and
        # a silent return here hid exactly that for four months (see 6f04e53).
        if odometer_km <= float(max_odometer_km):
            if declared:
                # A DECLARED odometer that never records is the expected steady
                # state for an app-accumulated total that drifts low (Torque's
                # ff120C) once any fuel record sits above it. Debug is too quiet
                # for that: the feature would produce nothing and say nothing.
                #
                # Throttled to once per VIN per day. Torque uploads every few
                # seconds, so an unthrottled warning is ~1,800 lines per
                # half-hour drive. Module-level because TelemetryService is
                # constructed per request, so instance state would never survive
                # to throttle anything.
                today_utc = utc_now().date()
                if _DECLARED_ODOMETER_WARNED.get(vin) != today_utc:
                    _DECLARED_ODOMETER_WARNED[vin] = today_utc
                    logger.warning(
                        "Declared odometer %s for %s read %d km, at or below the "
                        "existing maximum %s. No record written. If this repeats, "
                        "the declared parameter may be a trip counter or an "
                        "app-accumulated total rather than the vehicle odometer.",
                        odometer_key,
                        vin[:8],
                        odometer_km,
                        max_odometer_km,
                    )
            else:
                logger.debug(
                    "Skipped odometer %d km for %s (%s): not above existing max %s",
                    odometer_km,
                    vin[:8],
                    odometer_key,
                    max_odometer_km,
                )
            return

        # Cap date to today (don't allow future dates from device clock issues)
        today = household_today()
        record_date = min(timestamp.date(), today) if timestamp else today

        # LiveLink owns only its own rows. A day can hold several odometer rows
        # (a service visit and the tire mount it did, a tread reading above
        # this device's earlier one), so "the" row of the day is not a thing to
        # look up: asking for exactly one raised on every odometer-bearing
        # message of such a day and rolled the whole message back. The day's
        # own LiveLink row is updated; otherwise one is created beside whatever
        # the day holds, and no other source's row is ever modified. The guard
        # above admits only a reading above every stored one, so a created row
        # is always the day's highest.
        result = await self.db.execute(
            select(OdometerRecord)
            .where(
                OdometerRecord.vin == vin,
                OdometerRecord.date == record_date,
                OdometerRecord.source == "livelink",
            )
            .order_by(OdometerRecord.id.desc())
        )
        existing = result.scalars().first()

        if existing is not None:
            existing.odometer_km = Decimal(odometer_km)
            existing.notes = f"Auto-updated from LiveLink ({odometer_key})"
        else:
            # Create new odometer record
            odometer_record = OdometerRecord(
                vin=vin,
                date=record_date,
                odometer_km=Decimal(odometer_km),
                source="livelink",
                notes=f"Auto-recorded from LiveLink ({odometer_key})",
            )
            self.db.add(odometer_record)
            logger.info(
                "Created odometer record for %s: %d km from %s",
                vin[:8],
                odometer_km,
                odometer_key,
            )

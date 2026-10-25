"""Per-device wire units (R12) and the one unit-resolution step (R4).

WiCAN declares each key's unit and class once per cold boot, so they're kept
per device in `livelink_device_units`, not in process memory. Every write path
resolves a reading's unit through `DeviceUnitService.resolve_readings`, so live
and replayed readings of one key always land in the same unit.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import Decimal

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import is_sqlite
from app.models.livelink_device import LiveLinkDevice
from app.models.livelink_device_unit import SOURCE_LEGACY, SOURCE_WIRE, LiveLinkDeviceUnit
from app.models.livelink_parameter import LiveLinkParameter
from app.models.vehicle_telemetry import VehicleTelemetry, VehicleTelemetryLatest
from app.services.livelink_sources.base import Reading, WireUnit
from app.utils.datetime_utils import utc_now
from app.utils.logging_utils import sanitize_for_log
from app.utils.odometer_units import is_converted_odometer_key
from app.utils.units import UnitConverter
from app.utils.wire_units import CANONICAL_SPEED_UNIT, is_mph, mph_to_kmh

if is_sqlite:
    from sqlalchemy.dialects.sqlite import insert as dialect_insert
else:
    from sqlalchemy.dialects.postgresql import insert as dialect_insert

logger = logging.getLogger(__name__)

#: Same cap as the in-memory map (`declared_units`), per device.
MAX_KEYS_PER_DEVICE = 512

#: (device_id, param_key) already warned about a kept legacy row, so a device
#: that redeclares on every boot logs it once per process.
_LEGACY_KEPT_WARNED: set[tuple[str, str]] = set()

#: The alert lines on a parameter row, all compared in its stored unit.
_LINE_FIELDS = ("warning_min", "warning_max", "critical_min")


class DeviceUnitService:
    """Read and write a device's declared units, and resolve readings with them."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize with a database session."""
        self.db = db

    async def units_for(self, device_id: str) -> dict[str, WireUnit]:
        """Every unit the device has on file, by canonical key."""
        return {key: row for key, (row, _source) in (await self._stored(device_id)).items()}

    async def record(
        self,
        device: LiveLinkDevice,
        declared: Mapping[str, WireUnit],
        *,
        whole_profile: bool,
    ) -> None:
        """Upsert what a device declared; a later declaration wins, key by key.

        `whole_profile` (a WiCAN boot config) also drops the device's `wire`
        rows for keys it no longer declares, so renamed or junk keys can't
        fill the store for good. `legacy` rows always stay, and a `wire`
        declaration doesn't replace one for an odometer key that has history
        on this device: switching would strand the old records as a floor.
        """
        device_id = device.device_id
        rows = await self.db.execute(
            select(LiveLinkDeviceUnit.param_key, LiveLinkDeviceUnit.source).where(
                LiveLinkDeviceUnit.device_id == device_id
            )
        )
        held: dict[str, str] = {key: source for key, source in rows.all()}

        if whole_profile:
            stale = [k for k, src in held.items() if src == SOURCE_WIRE and k not in declared]
            if stale:
                await self.db.execute(
                    delete(LiveLinkDeviceUnit).where(
                        and_(
                            LiveLinkDeviceUnit.device_id == device_id,
                            LiveLinkDeviceUnit.param_key.in_(stale),
                        )
                    )
                )
                for key in stale:
                    del held[key]

        now = utc_now()
        values: list[dict[str, object]] = []
        dropped = 0
        for key, wire in declared.items():
            if held.get(key) == SOURCE_LEGACY and is_converted_odometer_key(
                key, device.odometer_param_key
            ):
                if await self._keeps_legacy(device, key):
                    self._warn_legacy_kept(device_id, key, wire.unit)
                    continue
            if key not in held and len(held) >= MAX_KEYS_PER_DEVICE:
                dropped += 1
                continue
            held[key] = SOURCE_WIRE
            values.append(
                {
                    "device_id": device_id,
                    "param_key": key,
                    "unit": wire.unit,
                    "param_class": wire.param_class,
                    "source": SOURCE_WIRE,
                    "created_at": now,
                    "updated_at": now,
                }
            )

        if values:
            stmt = dialect_insert(LiveLinkDeviceUnit).values(values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["device_id", "param_key"],
                set_={
                    "unit": stmt.excluded.unit,
                    "param_class": stmt.excluded.param_class,
                    "source": stmt.excluded.source,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            await self.db.execute(stmt)

        if dropped:
            # A warning, not debug: a full store locks new keys out until the
            # device's next boot replaces it.
            logger.warning(
                "Dropped %d declared unit(s) from %s: it already holds %d keys",
                dropped,
                sanitize_for_log(device_id),
                MAX_KEYS_PER_DEVICE,
            )

    async def _keeps_legacy(self, device: LiveLinkDevice, key: str) -> bool:
        """Whether a legacy row for ``key`` still guards readings it was written for.

        The bounded history predicate (the same one `update_device`'s 409
        uses), or migration 133's own fallback: a latest row for this key on
        the device's VIN, whenever it was written. That's the re-discovered
        device whose VIN's last reading predates it (Fable F5-5). Raw rows of
        other keys don't count against it: a re-discovered WiCAN sends COOLANT
        before it sends an odometer (Fable FB-2). 133's `odometer_param_key`
        clause isn't here: with nothing recorded under the old reading there's
        no floor to protect.
        """
        # Lazy: livelink_service is a much bigger import, and nothing else here needs it.
        from app.services.livelink_service import LiveLinkService

        if await LiveLinkService(self.db).device_has_odometer_history(device):
            return True
        # The history predicate matches the exact name set, narrower than the
        # scan that converted these keys (`ODOMETER_KM`), so ask about the key.
        raw = await self.db.execute(
            select(VehicleTelemetry.id)
            .where(
                VehicleTelemetry.device_id == device.device_id, VehicleTelemetry.param_key == key
            )
            .limit(1)
        )
        if raw.first() is not None:
            return True
        if not device.vin:
            return False
        latest = await self.db.execute(
            select(VehicleTelemetryLatest.id)
            .where(
                VehicleTelemetryLatest.vin == device.vin, VehicleTelemetryLatest.param_key == key
            )
            .limit(1)
        )
        return latest.first() is not None

    @staticmethod
    def _warn_legacy_kept(device_id: str, key: str, declared_unit: str | None) -> None:
        if (device_id, key) in _LEGACY_KEPT_WARNED:
            return
        _LEGACY_KEPT_WARNED.add((device_id, key))
        logger.warning(
            "Device %s declares %s in %s, but its history was read under the earlier "
            "unit; keeping that one so its odometer records stay comparable",
            sanitize_for_log(device_id),
            sanitize_for_log(key),
            sanitize_for_log(declared_unit),
        )

    async def _stored(self, device_id: str) -> dict[str, tuple[WireUnit, str]]:
        """The device's rows by key, with each one's source."""
        rows = await self.db.execute(
            select(
                LiveLinkDeviceUnit.param_key,
                LiveLinkDeviceUnit.unit,
                LiveLinkDeviceUnit.param_class,
                LiveLinkDeviceUnit.source,
            ).where(LiveLinkDeviceUnit.device_id == device_id)
        )
        return {key: (WireUnit(unit, cls), source) for key, unit, cls, source in rows.all()}

    @staticmethod
    def _pick(
        unit: str | None, param_class: str | None, stored: tuple[WireUnit, str] | None
    ) -> tuple[str | None, str | None]:
        """The one precedence rule: the reading's own > the stored row > none.

        Except a `legacy` row, which beats the reading's own. `record` runs
        first in `ingest` and only keeps a legacy row against a declaration
        when the device has odometer history, so a legacy row still here means
        the boot POST that declared otherwise must read the old unit too.
        """
        if stored is None:
            return unit, param_class
        row, source = stored
        if source == SOURCE_LEGACY:
            return row.unit, row.param_class
        return (
            unit if unit is not None else row.unit,
            param_class if param_class is not None else row.param_class,
        )

    async def resolve_readings(self, device_id: str, readings: Sequence[Reading]) -> list[Reading]:
        """Give each reading its unit and class, then store mph as km/h.

        A reading's own unit and class (this request's `config`, a topic map's
        `unit`) win, then the device's stored row, then nothing; a kept
        `legacy` row wins outright (`_pick`). A reading that resolves to mph is
        converted and carries `km/h` from here on (R4), and its parameter row
        follows (`_move_rows_to_kmh`).
        """
        stored = await self._stored(device_id) if readings else {}

        resolved: list[Reading] = []
        converted: set[str] = set()
        for reading in readings:
            unit, param_class = self._pick(
                reading.unit, reading.param_class, stored.get(reading.param_key)
            )
            if (unit, param_class) != (reading.unit, reading.param_class):
                reading = replace(reading, unit=unit, param_class=param_class)
            if is_mph(reading.unit):
                reading = replace(
                    reading, value=mph_to_kmh(reading.value), unit=CANONICAL_SPEED_UNIT
                )
                converted.add(reading.param_key)
            resolved.append(reading)

        if converted:
            await self._move_rows_to_kmh(converted)
        return resolved

    async def resolve_key_units(
        self, device_id: str, units: Mapping[str, str | None]
    ) -> dict[str, str | None]:
        """Each key's resolved unit, by the same rule as `resolve_readings`.

        For the odometer step, which has values and the units they came with
        but no `Reading`s. No mph step: an odometer is a distance.
        """
        stored = await self._stored(device_id) if units else {}
        return {key: self._pick(unit, None, stored.get(key))[0] for key, unit in units.items()}

    async def _move_rows_to_kmh(self, keys: set[str]) -> None:
        """A parameter row still labelled mph now holds km/h values.

        `auto_register_parameter` sets a unit only when it's empty, so an
        upgraded install's row would keep saying mph over km/h values. Its
        lines move with it, since they're compared in the stored unit.
        Unrounded, like every write path.
        """
        rows = await self.db.execute(
            select(LiveLinkParameter).where(LiveLinkParameter.param_key.in_(sorted(keys)))
        )
        for param in rows.scalars():
            if is_mph(param.unit):
                relabel_parameter(
                    param, CANONICAL_SPEED_UNIT, line_factor=UnitConverter.MILES_TO_KM
                )


def relabel_parameter(
    param: LiveLinkParameter, unit: str, *, line_factor: Decimal | None = None
) -> None:
    """Point a parameter row at the unit its values are stored in.

    `auto_register_parameter` only fills an empty unit, so a row an older
    version labelled otherwise keeps the old label over converted values.
    `line_factor` moves the alert lines too, for a row whose lines were
    written in the old unit (mph); an odometer row's never were.
    """
    old = param.unit
    param.unit = unit
    if line_factor is not None:
        for field in _LINE_FIELDS:
            line = getattr(param, field)
            if line is not None:
                setattr(param, field, float(Decimal(str(line)) * line_factor))
    logger.info(
        "Parameter %s relabelled from %s to %s%s",
        sanitize_for_log(param.param_key),
        sanitize_for_log(old),
        unit,
        " with its alert lines" if line_factor is not None else "",
    )

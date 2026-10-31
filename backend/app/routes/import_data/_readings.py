"""The odometer and hours readings an import collects, and the sync markers they carry."""

# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false

import logging
import re
from dataclasses import dataclass
from datetime import date as date_type
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.hours_sync import same_day_hours, sync_hours_from_record
from app.utils.hours_tolerance import hours_below
from app.utils.logging_utils import sanitize_for_log
from app.utils.odometer_sync import sync_odometer_from_record

logger = logging.getLogger(__name__)


#: Every sync marker: `auto_sync_marker` writes `[AUTO-SYNC from <source> #<id>]`
#: (utils/odometer_sync.py:51-59, utils/hours_sync.py:142), and the odometer
#: claim rule treats any note containing `[AUTO-SYNC from` as auto-synced
#: (odometer_sync.py:228).
_SYNC_MARKER = re.compile(r"\[AUTO-SYNC from [^\]]*\]")

#: The odometer sources a reading keeps through a move. The rest (fuel,
#: service_visit, def, the legacy service, and tire, tire_rotation, tire_set,
#: tire_mount, tire_dismount, tire_retire, tire_lone_dismount) name a record on
#: the instance that wrote them.
_PORTABLE_ODOMETER_SOURCES = frozenset({"manual", "livelink", "webhook"})


def _without_sync_marker(notes: Any) -> Any:
    """Notes with every sync marker taken out, None when nothing else is left.

    A copied marker made the reading look owned: the next same-day fill-up took
    it over, and a delete of a record with the marker's id removed it (N-2).
    """
    if not isinstance(notes, str):
        return notes
    return _SYNC_MARKER.sub("", notes).strip() or None


def _portable_odometer_source(source: Any) -> str:
    """The source an imported odometer reading keeps: its own if portable, else manual."""
    return source if source in _PORTABLE_ODOMETER_SOURCES else "manual"


@dataclass(frozen=True)
class _Reading:
    """One reading an imported record carries, and the record that owns it."""

    source_type: str
    source_id: int
    value: Decimal


class _ImportReadings:
    """The readings an import's records carry, synced once a day at its end (R3).

    The create paths sync each record as it's written. An import syncs once per
    day and track, with that day's highest reading: the odometer sync takes over
    an auto-synced row on its date, so syncing every row let file order pick the
    stored value. A tie keeps the record added first.
    """

    def __init__(self) -> None:
        self._odometer: dict[date_type, _Reading] = {}
        self._hours: dict[date_type, _Reading] = {}

    def add(
        self,
        source_type: Literal["fuel", "service_visit", "def"],
        source_id: int,
        day: date_type,
        *,
        odometer_km: Decimal | None,
        engine_hours: Decimal | None = None,
    ) -> None:
        """Note one written record's readings. Only fuel and service visits carry hours."""
        for readings, value in ((self._odometer, odometer_km), (self._hours, engine_hours)):
            if value is None:
                continue
            best = readings.get(day)
            if best is None or value > best.value:
                readings[day] = _Reading(source_type, source_id, value)

    async def apply(self, db: AsyncSession, vin: str, *, claim: bool) -> None:
        """Sync each day's reading. A failure is logged and the imported rows stay.

        With `claim`, the odometer sync may take over a same-day automatic or
        LiveLink row (the create paths' rule, kept for the third-party importers).
        Without it, nothing stored is touched: a day that already reads at or
        above the figure gets nothing, any other day a row of its own (R1-H2).
        """
        for day, reading in self._odometer.items():
            try:
                async with db.begin_nested():
                    await sync_odometer_from_record(
                        db=db,
                        vin=vin,
                        date=day,
                        odometer_km=reading.value,
                        source_type=reading.source_type,
                        source_id=reading.source_id,
                        commit=False,
                        claim_other_records=claim,
                    )
            except Exception as e:
                # Derived data only. Escaping would reach get_db's handler, which
                # rolls back the outer transaction and the whole import with it.
                logger.warning(
                    "Odometer sync failed for imported %s record %s: %s",
                    reading.source_type,
                    reading.source_id,
                    sanitize_for_log(e),
                )
        for day, reading in self._hours.items():
            try:
                async with db.begin_nested():
                    # The hours sync has no same-day rule, so a reading the file's
                    # hours section already restored would land twice (T-1). This
                    # is the odometer's non-claiming rule, applied to hours.
                    same_day = await same_day_hours(db, vin, day)
                    if any(not hours_below(row.engine_hours, reading.value) for row in same_day):
                        continue
                    await sync_hours_from_record(
                        db=db,
                        vin=vin,
                        date=day,
                        engine_hours=reading.value,
                        source_type=reading.source_type,
                        source_id=reading.source_id,
                        commit=False,
                    )
            except Exception as e:
                logger.warning(
                    "Hours sync failed for imported %s record %s: %s",
                    reading.source_type,
                    reading.source_id,
                    sanitize_for_log(e),
                )

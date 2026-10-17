"""Tire tracking business logic — readings, wear projection, reminder hooks."""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Iterable, Sequence
from datetime import timedelta
from decimal import Decimal
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.hours import HoursRecord
from app.models.odometer import OdometerRecord
from app.models.reminder import Reminder
from app.models.tire import Tire, TireMountPeriod, TireReading, TireSet
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.tire import (
    HistoryFaultResponse,
    MountPeriodCreate,
    MountPeriodResponse,
    MountPeriodUpdate,
    TireCreate,
    TireCreateAndMountRequest,
    TireDismountRequest,
    TireListResponse,
    TireMountRequest,
    TireReadingCreate,
    TireReadingResponse,
    TireReadingUpdate,
    TireResponse,
    TireRotationRequest,
    TireUpdate,
)
from app.services.hours_service import latest_engine_hours_and_date
from app.services.reminder_service import start_readings
from app.services.tire_history import (
    DistanceFormatter,
    FaultMap,
    distance_formatter,
    fault_map,
    new_or_touched_faults,
    odometer_contradictions,
    reading_contradiction_message,
    reading_contradictions,
    validate_period_history,
)
from app.services.tire_results import (
    DistanceResult,
    DistanceStatus,
    IntervalResult,
    IntervalStatus,
    WearResult,
    WearStatus,
)
from app.services.usage_axis import DISTANCE, HOURS, UsageAxis, VehicleAxes
from app.services.vehicle_lock import lock_vehicle_for_write
from app.utils.hours_sync import publish_marked_hours, same_day_hours
from app.utils.household_time import household_today
from app.utils.logging_utils import sanitize_for_log
from app.utils.odometer_sync import (
    auto_sync_marker,
    same_day_records,
    sync_odometer_from_record,
)
from app.utils.render_context import render_context_for_request
from app.utils.unit_adapters import adapter_for

logger = logging.getLogger(__name__)

# `source_type` for the odometer readings the tire paths publish. Two of them,
# and the split decides what happens when a tire is deleted: a mount, dismount,
# retire or reading odometer exists because of ONE tire and goes with it, while
# a rotation's is a reading of the VEHICLE taken while several tires were on
# it. Deleting one of those tires does not make the reading untrue, and
# cascading it would break the distance figure for every other tire in the same
# rotation. Both fit `odometer_records.source` VARCHAR(20) -- a length
# PostgreSQL enforces and SQLite does not.
ODOMETER_SOURCE_TIRE = "tire"
ODOMETER_SOURCE_ROTATION = "tire_rotation"
ODOMETER_SOURCE_SET = "tire_set"

#: Per-period markers, so an odometer record can say WHICH event published it.
#: `ODOMETER_SOURCE_TIRE` is what a tread reading publishes with, keyed by the
#: tire; these two are keyed by the period, which is what lets the period
#: editor move the right record and only that one. Rotation and set fit keep
#: their vehicle-level markers: one reading covers several tires.
ODOMETER_SOURCE_TIRE_MOUNT = "tire_mount"
ODOMETER_SOURCE_TIRE_DISMOUNT = "tire_dismount"


async def publish_tire_odometer(
    db: AsyncSession,
    vin: str,
    when: dt.date,
    odometer_km: Decimal | None,
    source_type: str,
    source_id: int,
) -> None:
    """Record a tire event's odometer as a reading of the VEHICLE, owning only its own.

    The one door every tire path publishes through: mount, create and mount,
    dismount, retire, rotation, set fit, the period editor, add past period
    and tread readings. A tire event only ever creates, updates or deletes a
    record carrying its own marker, `auto_sync_marker(source_type,
    source_id)`, and never touches any other. On `when`:

    1. A record with that marker has its value updated. Under the tire's own
       marker a figure below it, beyond the same-reading tolerance, leaves
       it: every reading of the tire that day shares that marker, so the
       record keeps the highest (#224) and only a reading delete or edit
       lowers it (`_withdraw_reading_usage`). A set fit or rotation
       published again lower is taken as a correction and lowers its record;
       the period editor moves a period's record itself.
    2. Otherwise, when another record on the day (manual, a service visit's,
       a fuel-up's, LiveLink's, another tire event's) reads at or above the
       figure, within the same-reading tolerance, nothing is published: the
       vehicle already has a reading at least as high for that day, and the
       tire's odometer stays on its period or reading row.
    3. Otherwise a record with the event's marker is created, beside any
       lower ones. A service visit at 50,000 km and the mount it did at
       50,012 km on one day leave both, and the mount's figure, being the
       day's highest, is the vehicle's current reading (the highest reading
       on the latest date, `odometer_service.latest_odometer_km_and_date`),
       so the new tire's distance starts at zero instead of reading as the
       odometer running backwards.

    Why not the synchroniser's same-day policy that fuel and service visits
    use: a tire event's record is later moved by the period editor and
    deleted with the tire, both by marker. A service visit's reading that a
    mount had re-marked moved with the period to another date, leaving the
    vehicle's odometer history running backwards, and would have gone with
    the tire on delete.

    Composed into the caller's transaction (`commit=False`): a commit in the
    middle of a mount, a rotation or a retire splits the operation in half.
    A null odometer is a no-op.
    """
    await _publish_tire_usage(db, vin, when, odometer_km, source_type, source_id, DISTANCE)


async def publish_tire_hours(
    db: AsyncSession,
    vin: str,
    when: dt.date,
    engine_hours: Decimal | None,
    source_type: str,
    source_id: int,
) -> None:
    """`publish_tire_odometer` for the hour meter: same marker, same rules, on `hours_records`.

    Under the tire's own marker a lower figure leaves its same-day row here too (#224).
    """
    await _publish_tire_usage(db, vin, when, engine_hours, source_type, source_id, HOURS)


async def _owned_usage_record(
    db: AsyncSession, vin: str, axis: UsageAxis, marker: str
) -> OdometerRecord | HoursRecord | None:
    """The newest row on `axis` carrying `marker`, on any date."""
    if axis.is_hours:
        return (
            (
                await db.execute(
                    select(HoursRecord)
                    .where(HoursRecord.vin == vin, HoursRecord.notes == marker)
                    .order_by(HoursRecord.id.desc())
                )
            )
            .scalars()
            .first()
        )
    return (
        (
            await db.execute(
                select(OdometerRecord)
                .where(OdometerRecord.vin == vin, OdometerRecord.notes == marker)
                .order_by(OdometerRecord.id.desc())
            )
        )
        .scalars()
        .first()
    )


async def _same_day_usage(
    db: AsyncSession, vin: str, axis: UsageAxis, when: dt.date
) -> Sequence[OdometerRecord | HoursRecord]:
    """Every row on `axis` for `when`, newest first."""
    if axis.is_hours:
        return await same_day_hours(db, vin, when)
    return await same_day_records(db, vin, when)


def _usage_value(record: OdometerRecord | HoursRecord) -> Decimal:
    return record.engine_hours if isinstance(record, HoursRecord) else record.odometer_km


def _move_usage_record(record: OdometerRecord | HoursRecord, when: dt.date, value: Decimal) -> None:
    record.date = when
    if isinstance(record, HoursRecord):
        record.engine_hours = value
    else:
        record.odometer_km = value


async def _publish_tire_usage(
    db: AsyncSession,
    vin: str,
    when: dt.date,
    value: Decimal | None,
    source_type: str,
    source_id: int,
    axis: UsageAxis,
) -> None:
    """The one door behind both tire publishers: `publish_tire_odometer`'s rules, on `axis`.

    Only the tire's own marker holds back a lower figure, since it stands for
    every event of that tire on the day. A set fit or rotation published lower
    the same day is taken as a correction and goes through.
    """
    if value is None:
        return
    if source_type == ODOMETER_SOURCE_TIRE:
        marker = auto_sync_marker(source_type, source_id)
        same_day = await _same_day_usage(db, vin, axis, when)
        own = next((record for record in same_day if record.notes == marker), None)
        if own is not None and axis.below(value, _usage_value(own)):
            return
    if axis.is_hours:
        await publish_marked_hours(db, vin, when, value, source_type, source_id)
    else:
        await sync_odometer_from_record(
            db, vin, when, value, source_type, source_id, commit=False, claim_other_records=False
        )


def normalise_storage_location(value: str | None) -> str | None:
    """A storage location as stored: stripped, and blank is no location.

    One rule for every writer that takes one (create, create and mount, edit,
    dismount, retire). The creates used to store the text as sent while edit
    and dismount stripped it, so the same padded input read back differently
    depending on which form had saved it.
    """
    if value is None:
        return None
    return value.strip() or None


UNTRACKED_DISTANCE = (
    "This vehicle doesn't track distance, so a tire can't take an odometer reading. "
    "Use the hour meter instead."
)
UNTRACKED_HOURS = (
    "This vehicle doesn't track engine hours, so a tire can't take an hour meter reading."
)
MEASURES_NOTHING = "A reading needs a tread depth, a pressure, or both"


def refuse_untracked(
    axes: VehicleAxes,
    *,
    odometers: Iterable[Decimal | None] = (),
    hours: Iterable[Decimal | None] = (),
) -> None:
    """422 a tire write carrying a figure for an axis the vehicle doesn't track (#217).

    Runs before anything is written. A null is fine on either axis.
    """
    if not axes.tracks("distance") and any(v is not None for v in odometers):
        raise HTTPException(status_code=422, detail=UNTRACKED_DISTANCE)
    if not axes.tracks("hours") and any(v is not None for v in hours):
        raise HTTPException(status_code=422, detail=UNTRACKED_HOURS)


def past_retirement(retired_on: dt.date) -> str:
    """The 409 for a period that runs past the tire's retirement (G4-71)."""
    return f"This tire was retired on {retired_on.isoformat()}. A mount period can't run past that."


def retired_before_history(last_day: dt.date) -> str:
    """The 409 for a retire dated before the tire's last known period date (G4-71)."""
    return (
        f"This tire's mount history runs to {last_day.isoformat()}, "
        "so it can't be retired before that."
    )


def last_known_day(periods: Iterable[TireMountPeriod]) -> dt.date | None:
    """The latest mount or dismount date these periods know, if any."""
    return max(
        (
            day
            for period in periods
            for day in (period.mounted_on, period.dismounted_on)
            if day is not None
        ),
        default=None,
    )


async def apply_mount_moves(
    db: AsyncSession,
    *,
    vacate: Sequence[Tire],
    assign: Sequence[tuple[Tire, str]],
    when: dt.date,
    odometer_km: Decimal | None,
    engine_hours: Decimal | None = None,
    notes: str | None = None,
) -> None:
    """Take tires off corners and put tires onto corners, in two phases.

    **Why two phases.** `uq_tires_vin_position` is an IMMEDIATE unique index on
    both dialects, so assigning one tire at a time fails the moment a
    destination is still occupied -- which for a rotation or a seasonal swap is
    always. An X-pattern collides on the very first move even though the
    requested FINAL arrangement is perfectly legal. So: clear every affected
    `tires.position` and close every affected period, FLUSH, then assign the new
    positions and open the new periods. Deferring the constraint is not an
    option; SQLite has no `DEFERRABLE INITIALLY DEFERRED`.

    A tire in `vacate` and not in `assign` ends up stored, which is what a
    seasonal swap does to the set coming off. A tire in `assign` and not in
    `vacate` is a stored tire being fitted, and has no open period to close.

    Extracted when tire sets arrived, because the alternative was a second copy
    of the vacate/flush/assign dance -- the subtlest thing in the tire service,
    and the one whose absence does not fail loudly but corrupts an arrangement.

    Appends to each tire's `mount_periods` rather than `db.add`, so the
    caller can validate the resulting history on the collection it already
    holds.

    Args:
        vacate: Tires to take off, closing each one's open period at
            `when`/`odometer_km`.
        assign: `(tire, position)` pairs to fit, opening a period for each.
        when: The date both halves are recorded at.
        odometer_km: The vehicle's odometer, bounding both halves.
        engine_hours: The vehicle's hour meter, bounding both halves.
        notes: Free text copied onto every period this opens.
    """
    vacate_ids = [tire.id for tire in vacate]
    open_periods = {}
    if vacate_ids:
        open_periods = {
            period.tire_id: period
            for period in (
                await db.execute(
                    select(TireMountPeriod).where(
                        TireMountPeriod.tire_id.in_(vacate_ids),
                        TireMountPeriod.dismounted_on.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        }

    # ---- Phase 1: vacate. -----------------------------------------------
    for tire in vacate:
        tire.position = None
        period = open_periods.get(tire.id)
        if period is not None:
            period.dismounted_on = when
            period.dismounted_odometer_km = odometer_km
            period.dismounted_hours = engine_hours
    # The flush is the point of the split: without it the assignments below
    # race the old values still sitting in the unique index.
    await db.flush()

    # ---- Phase 2: assign. -----------------------------------------------
    for tire, position in assign:
        tire.position = position
        tire.mount_periods.append(
            TireMountPeriod(
                tire_id=tire.id,
                position=position,
                mounted_on=when,
                mounted_odometer_km=odometer_km,
                mounted_hours=engine_hours,
                is_assumed=False,
                notes=notes,
            )
        )
    # Ids for the new periods, and the resulting set in every tire's
    # collection, for the validation each caller runs next.
    await db.flush()


def distance_on_tire(
    tire: Tire, current_odometer: Decimal | None, axis: UsageAxis = DISTANCE
) -> DistanceResult:
    """Distance driven ON THIS TIRE, summed over its mount periods.

    This is the calculation the whole mount-period model exists for. The old
    one took the raw odometer delta between two readings, which for anyone
    running a second seasonal set counts the distance driven on the OTHER set.

    `axis` picks the columns; `current_odometer` is the vehicle's current figure
    on that axis (#217).

    Args:
        tire: The tire, with `mount_periods` loaded.
        current_odometer: The vehicle's latest odometer reading, used as the
            upper bound of any period still open. None when the vehicle has no
            odometer record at all, which makes an open period unbounded.

    Returns:
        A `DistanceResult` whose `status` says why a figure is or is not
        available. Never a bare zero: "this tire has never rolled" and "this
        tire rolled zero kilometres" are different answers.
    """
    periods = list(tire.mount_periods or [])
    if not periods:
        return DistanceResult(status=DistanceStatus.NO_PERIODS)

    # A spare accrues nothing: it is in the trunk while the vehicle drives.
    rolling = [p for p in periods if p.position != "SPARE"]
    if not rolling:
        return DistanceResult(status=DistanceStatus.SPARE_ONLY)

    known = Decimal("0")
    earliest: dt.date | None = None
    contributed = 0
    blocking: list[int] = []

    for period in rolling:
        start = axis.mounted(period)
        end = axis.dismounted(period) if period.dismounted_on is not None else current_odometer
        if start is None or end is None:
            blocking.append(period.id)
            continue
        if axis.below(end, start):
            return DistanceResult(
                status=DistanceStatus.ODOMETER_ROLLBACK,
                blocking_period_ids=[period.id],
            )
        # Zero, not a few hundred metres below it, when the two bounds are one
        # reading in two spellings (a figure saved before v3.4.0 and the same
        # figure typed today): within the band that is a period that rolled
        # nothing, as `distance_between` counts an interval with no length.
        # The zero carries the axis's column scale, so a figure made of it
        # alone serialises like every other distance ("0.00", not "0").
        known += max(end - start, axis.zero)
        contributed += 1
        # Only a period that CONTRIBUTED can date the known figure, and its
        # `mounted_on` may still be null on a migrated assumed period.
        if period.mounted_on is not None:
            earliest = period.mounted_on if earliest is None else min(earliest, period.mounted_on)

    if contributed == 0:
        # Every migrated tire, on upgrade day. NOT `incomplete`: there is no
        # subtotal to show, and "0 km since an unknown date" is worse than
        # saying nothing.
        return DistanceResult(status=DistanceStatus.NOTHING_BOUNDED, blocking_period_ids=blocking)
    if blocking:
        return DistanceResult(
            status=DistanceStatus.INCOMPLETE,
            known_value=known,
            known_since=earliest,
            blocking_period_ids=blocking,
        )
    return DistanceResult(
        status=DistanceStatus.COMPLETE,
        all_time_value=known,
        known_value=known,
        known_since=earliest,
    )


def _overlapping_period_ids(
    contributions: list[tuple[Decimal, Decimal, int]], axis: UsageAxis = DISTANCE
) -> list[int]:
    """Ids of contributing spans that claim the same kilometres.

    Touching endpoints are not an overlap: a dismount at 12,000 and a
    remount at 12,000 is what a rotation looks like. Neither is an
    intersection within the same-reading band (`app.utils.odometer_tolerance`):
    a dismount typed at 89,044 mi today and a remount at a service visit's
    figure for 89,044 mi saved before v3.4.0 sit 0.36 km apart and are one
    reading. The history validator accepts that boundary, so counting it here
    would withhold the distance of every such tire as an overlap. Both
    contributions are summed as they are, so the total can exceed the span by
    up to the band at each such boundary. Only an intersection beyond the
    band counts.

    Tracks the running maximum end rather than comparing neighbours, so a
    period nested wholly inside an earlier one is caught even though the
    span between them in sorted order does not intersect. The maximum itself
    is kept by a plain comparison: one that moved only once an end cleared
    the band would lag a span ending within the band above it, and miss a
    later span overlapping that one beyond the band.

    The band is `axis`'s: on the hour meter, `app.utils.hours_tolerance` (#217).
    """
    clashing: set[int] = set()
    running_hi: Decimal | None = None
    running_id: int | None = None
    for lo, hi, period_id in sorted(contributions, key=lambda c: c[0]):
        if running_hi is not None and running_id is not None and axis.below(lo, running_hi):
            clashing.update({running_id, period_id})
        if running_hi is None or hi > running_hi:
            running_hi, running_id = hi, period_id
    return sorted(clashing)


def _odometer_goes_backwards(
    periods: list[TireMountPeriod],
    readings: tuple[TireReading, ...],
    axis: UsageAxis = DISTANCE,
) -> list[int]:
    """C5: periods whose odometer bounds contradict a reading's date, by id.

    The rule, its four implications and why every date comparison is strict
    live on `tire_history.odometer_contradictions`, which yields the offending
    (period, reading) pairs. The projection needs only which periods to
    withhold a figure over; the write-time validator names the reading from
    the same pairs, so the two cannot disagree about what contradicts.
    """
    return sorted({period.id for period, _ in odometer_contradictions(periods, readings, axis)})


def distance_between(
    tire: Tire,
    older: TireReading,
    newer: TireReading,
    current_odometer: Decimal | None,
    axis: UsageAxis = DISTANCE,
) -> IntervalResult:
    """Distance driven on this tire BETWEEN two readings.

    Not the same question as `distance_on_tire`, which totals a lifetime.
    A wear RATE needs the distance over which the tread actually fell, and
    for anyone running a second set those two numbers differ by everything
    driven on the other set.

    The intersection is proved from the NEAR bound only (C2): a period whose
    end is at or below the older reading, or whose start is at or above the
    newer one (each judged outside the same-reading band), contributes
    nothing and blocks nothing, whatever the bound on its far side is. That single rule is what lets a tire migrated by 097
    recover: its assumed period has a null START, and a recorded dismount
    gives it an END that puts it outside the interval.

    Args:
        tire: The tire, with `mount_periods` loaded.
        older: The earlier tread-bearing reading. Its `odometer_km` is the
            lower bound of the interval.
        newer: The later tread-bearing reading, and the upper bound.
        current_odometer: The vehicle's latest odometer, used for a period
            still open. May be None on a vehicle with no readings.
        axis: Which columns and band to read (#217). On the hours axis every
            figure here, `current_odometer` and `km` included, is hours.

    Returns:
        An `IntervalResult`. `km` is populated only for COMPLETE; every
        other status withholds the figure rather than publishing a subtotal,
        because this number is the DENOMINATOR of a wear rate and a wrong
        one is wrong in both directions: too small understates remaining
        life, and too large overstates it, which is the dangerous direction
        and is exactly the defect this replaces.
    """
    a_odo, b_odo = axis.reading(older), axis.reading(newer)
    # Every odometer ordering below is judged outside the same-reading band
    # (`app.utils.odometer_tolerance`), the one the history validator uses, so
    # a boundary the validator accepts never withholds a figure here. Two
    # readings within the band of each other are one odometer, not a distance.
    if a_odo is None or b_odo is None or not axis.below(a_odo, b_odo):
        return IntervalResult(status=IntervalStatus.NO_DISTANCE)

    periods = list(tire.mount_periods or [])
    if not periods:
        return IntervalResult(status=IntervalStatus.NO_PERIODS)
    rolling = [p for p in periods if p.position != "SPARE"]
    if not rolling:
        return IntervalResult(status=IntervalStatus.SPARE_ONLY)

    blocking: list[int] = []
    faulted: list[int] = []
    contributions: list[tuple[Decimal, Decimal, int]] = []

    for period in rolling:
        start = axis.mounted(period)
        if period.dismounted_on is not None:
            end = axis.dismounted(period)
        elif current_odometer is not None:
            # C4. An open period has no recorded dismount, so a reading at
            # `b_odo` is itself evidence the tire was mounted at `b_odo`.
            # Clipping to `current_odometer` alone loses real distance
            # whenever a reading outruns the vehicle's latest record.
            end = max(current_odometer, b_odo)
        else:
            end = b_odo

        # C3, checked BEFORE C2's disjointness proof. A bound cannot be used
        # to prove a period disjoint when the bounds are known-corrupt: a
        # period mounted at 20,000 and dismounted at 5,000 has `end <= a_odo`
        # for almost any interval, so C2 would wave it through as "outside"
        # instead of flagging it, and a second, genuine contributor would
        # then publish a confident figure over a history already known to be
        # faulted. Both bounds must be non-null for "reversed" to mean
        # anything; a period missing one still falls through to C2 and then
        # to the null-bound handling below, unchanged.
        if start is not None and end is not None and axis.below(end, start):
            # NOT `max(0, hi - lo)`: clamping contributes a silent zero for a
            # faulted period while another period supplies a positive total,
            # publishing a confident figure over known-corrupt data.
            faulted.append(period.id)
            continue

        # C2. Provable disjointness, from the near bound only. A near bound
        # within the band of the reading is at the reading.
        if end is not None and not axis.above(end, a_odo):
            continue
        if start is not None and not axis.below(start, b_odo):
            continue

        # Past here the period may overlap, so both bounds are load-bearing.
        # A pair reversed beyond the band was already caught above; one
        # reversed within it gives `hi <= lo` below and contributes nothing.
        if start is None or end is None:
            blocking.append(period.id)
            continue

        lo, hi = max(a_odo, start), min(b_odo, end)
        if hi > lo:
            contributions.append((lo, hi, period.id))

    overlapping = _overlapping_period_ids(contributions, axis)
    if overlapping:
        return IntervalResult(
            status=IntervalStatus.OVERLAPPING_HISTORY, blocking_period_ids=overlapping
        )
    if faulted:
        return IntervalResult(
            status=IntervalStatus.ODOMETER_ROLLBACK, blocking_period_ids=sorted(faulted)
        )
    # C5, here and not earlier. Overlapping periods and reversed bounds are
    # monotonicity violations too, so running this first would answer
    # HISTORY_CONTRADICTS for both and swallow the specific diagnosis. All
    # three suppress, so precedence changes no number, only the repair the
    # user is pointed at.
    contradicting = _odometer_goes_backwards(rolling, (older, newer), axis)
    if contradicting:
        return IntervalResult(
            status=IntervalStatus.HISTORY_CONTRADICTS, blocking_period_ids=contradicting
        )
    if blocking:
        return IntervalResult(
            status=IntervalStatus.UNVERIFIED, blocking_period_ids=sorted(blocking)
        )
    total = sum((hi - lo for lo, hi, _ in contributions), Decimal("0"))
    if total <= 0:
        return IntervalResult(status=IntervalStatus.NO_DISTANCE)
    return IntervalResult(status=IntervalStatus.COMPLETE, km=total)


def project_wear(
    tire: Tire,
    current_odometer: Decimal | None,
    readings: list[TireReading] | None = None,
    axis: UsageAxis = DISTANCE,
) -> WearResult:
    """Estimate remaining tread life, with the reason when there is none.

    Two changes from the pre-v3.3.0 `_project_wear`, both of which were
    producing wrong or missing numbers in production:

    1. It is **period-aware**. The old one used the raw odometer delta between
       the two readings as distance driven on this tire. That is only correct
       for someone who has never had a second set, and it errs HIGH -- the
       dangerous direction. Where the mount history cannot support the figure
       it is now withheld (`UNVERIFIED_MOUNT_HISTORY`) rather than published
       with an "estimate" badge.

    2. It **sorts its own readings**. `_sync_low_tread_reminder` passed them
       unsorted, so `readings[0]` was the OLDEST, `tread_delta` came out
       negative, and the low-tread projection has been silently missing from
       every reminder. Selection moved inside so this surface and the reminder
       quote the same number by construction.

    Args:
        tire: The tire, with `mount_periods` loaded.
        current_odometer: The vehicle's latest odometer, for open periods.
        readings: Override for the reading list; defaults to the tire's own.
            Passed in by callers that already loaded them.
        axis: Which columns the rate runs on (#217). On the hours axis
            `km_remaining` holds hours.

    Returns:
        A `WearResult`. Its `status` is exhaustive: every current null exit of
        the old function maps to a named member, so a caller can say WHICH
        input is missing instead of rendering one message for five states.
    """
    candidates = sorted(
        [r for r in (readings if readings is not None else tire.readings or [])],
        key=lambda r: r.recorded_at,
        reverse=True,
    )
    min_tread = tire.min_tread_mm

    if min_tread is None:
        # No 2.0 fallback: the 2.0 is a COLUMN default applied at insert, not
        # to a row that already holds null.
        return WearResult(status=WearStatus.NO_MINIMUM_SET)

    with_tread = [r for r in candidates if r.tread_depth_mm is not None]

    # C7. The threshold is a SAFETY statement and needs no distance to be
    # true, so it is decided before every rate prerequisite. It used to sit
    # below the distance gate, which meant a tire measured at 1.5 mm against
    # a 2.0 mm minimum reported "add an odometer" while the low-tread
    # reminder was already raised against it. C8: the tread read here is
    # `tire.tread_depth_mm`, the same scalar the card renders and
    # `_sync_low_tread_reminder` tests, so the three cannot disagree.
    tread_now = tire.tread_depth_mm
    if tread_now is not None and tread_now <= min_tread:
        # Only a reading that ITSELF measured at or below the minimum may
        # date this result. `tire.tread_depth_mm` can be set directly
        # through `TireUpdate` with no reading logged at all, so the newest
        # reading on file may still be healthy and months old; reusing its
        # date would attribute the threshold crossing to a measurement that
        # never crossed it, which reads as a measurement that never
        # happened -- the same failure the missing `utc_now()` fallback
        # below already guards against.
        newest = with_tread[0] if with_tread else None
        dating_reading = (
            newest if newest is not None and newest.tread_depth_mm <= min_tread else None
        )
        return WearResult(
            status=WearStatus.AT_OR_BELOW_MINIMUM,
            km_remaining=Decimal("0"),
            # No `utc_now()` fallback either: an invented date would read as
            # a measurement that never happened.
            wear_date=dating_reading.recorded_at if dating_reading is not None else None,
        )

    if len(with_tread) < 2:
        return WearResult(status=WearStatus.INSUFFICIENT_READINGS)

    newer, older = with_tread[0], with_tread[1]
    if axis.reading(newer) is None or axis.reading(older) is None:
        return WearResult(status=WearStatus.NO_READING_ODOMETERS)

    newer_tread, older_tread = newer.tread_depth_mm, older.tread_depth_mm
    if newer_tread is None or older_tread is None:  # pragma: no cover - filtered above
        return WearResult(status=WearStatus.INSUFFICIENT_READINGS)

    tread_delta = older_tread - newer_tread
    if tread_delta <= 0:
        # Flat or increasing tread. Distinct from "you have not driven on this
        # tire": the prompts differ, and the old code could not tell a caller
        # which of the two had happened.
        return WearResult(status=WearStatus.TREAD_NOT_DECREASING)

    # The distance driven on THIS TIRE between THESE TWO READINGS.
    #
    # The pre-v3.3.1 code called `distance_on_tire`, read its STATUS as a
    # gate, discarded its VALUE, and then took the raw odometer span. That
    # is period-GATED, not period-aware: `DistanceStatus.COMPLETE` is a
    # LIFETIME predicate, not "both readings fall in one period", so the
    # guard admitted exactly the two-set owner it was built to exclude.
    interval = distance_between(tire, older, newer, current_odometer, axis)
    if interval.status is IntervalStatus.COMPLETE and interval.km is not None:
        km_delta = interval.km
    elif interval.status is IntervalStatus.UNVERIFIED:
        return WearResult(
            status=WearStatus.UNVERIFIED_MOUNT_HISTORY,
            blocking_period_ids=interval.blocking_period_ids,
        )
    else:
        # Every remaining status is a fault, a contradiction or an empty
        # intersection. All of them withhold the number and the card already
        # renders one string for both wear statuses, so no copy is needed.
        return WearResult(
            status=WearStatus.NO_DISTANCE_ON_TIRE,
            blocking_period_ids=interval.blocking_period_ids,
        )

    if km_delta <= 0:
        return WearResult(status=WearStatus.NO_DISTANCE_ON_TIRE)

    remaining_tread = newer_tread - min_tread
    if remaining_tread <= 0:
        # At or past the threshold. This is the SAFETY case: it carries a
        # number and a date, and the reminder fires on it.
        #
        # NOT dead code despite the hoisted check above: that check reads
        # `tire.tread_depth_mm` (the tire's own scalar), this reads
        # `newer_tread` (the newest READING's tread), and the two can
        # disagree. `tread_depth_mm` is nullable and `TireUpdate` accepts an
        # explicit null (`update_tire` uses `exclude_unset`, so sending null
        # clears it), so a user who clears the tire's scalar tread while
        # readings below the minimum remain gets a None `tread_now` above,
        # which skips the hoisted check, and lands here instead.
        return WearResult(
            status=WearStatus.AT_OR_BELOW_MINIMUM,
            km_remaining=Decimal("0"),
            wear_date=newer.recorded_at,
        )

    mm_per_km = tread_delta / km_delta
    km_left = remaining_tread / mm_per_km
    day_delta = (newer.recorded_at - older.recorded_at).days
    wear_date = None
    if day_delta > 0:
        km_per_day = km_delta / Decimal(day_delta)
        if km_per_day > 0:
            days_left = int(km_left / km_per_day)
            # A near-zero wear rate lands past the calendar, and `timedelta`
            # would raise OverflowError.
            if days_left <= (dt.date.max - newer.recorded_at).days:
                wear_date = newer.recorded_at + timedelta(days=max(days_left, 0))
    # `wear_date` stays None for same-day readings, or for a date past the
    # calendar: the km figure is still valid, so status is PROJECTED and the
    # date is simply unavailable.
    return WearResult(
        status=WearStatus.PROJECTED,
        km_remaining=km_left.quantize(Decimal("0.1")),
        wear_date=wear_date,
    )


def _same_measure(a: Decimal | None, b: Decimal | None) -> bool:
    """Whether two stored measurements are the same known value.

    As Decimals, so "7.0" from a request and "7.00" from a `Numeric(5, 2)`
    column compare equal. An unknown on either side is never the same.
    """
    return a is not None and b is not None and Decimal(a) == Decimal(b)


Measure = Literal["tread_depth_mm", "pressure_kpa"]
#: What a reading measures about the tire. The odometer and hours are context, not these.
MEASURES: tuple[Measure, ...] = ("tread_depth_mm", "pressure_kpa")


def _newest_with(readings: Iterable[TireReading], measure: Measure) -> TireReading | None:
    """The newest reading that takes `measure`, by (recorded_at, id) as `delete_reading` orders."""
    return max(
        (r for r in readings if getattr(r, measure) is not None),
        key=lambda r: (r.recorded_at, r.id or 0),
        default=None,
    )


def _newest_value(readings: Iterable[TireReading], measure: Measure) -> Decimal | None:
    """The newest reading's value of `measure`, or None when no reading takes it."""
    newest = _newest_with(readings, measure)
    return getattr(newest, measure) if newest is not None else None


def _low_tread_title(position: str | None) -> str:
    """Title for a low-tread reminder.

    Never renders `None` as a corner. `Tire.position` became nullable in
    migration 097, and the f-string produced the literal "Tire tread low
    (None)" for a stored tire, which two stored tires then collided on.
    Identity is `tire_id` now, so the title is display text only, but it is
    still read by a human in the calendar and the notification.
    """
    return f"Tire tread low ({position})" if position else "Tire tread low (in storage)"


class TireService:
    """CRUD + wear projection + low-tread reminder hooks."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _current_odometer(self, vin: str) -> Decimal | None:
        """The vehicle's latest odometer reading, in canonical km.

        Used as the upper bound for any mount period still open. There is no
        odometer column on `Vehicle` -- it is a relationship -- so this is a
        query, and it legitimately returns None for a vehicle that has never
        had a reading. That is its own empty state, not a zero: every open
        period on such a vehicle is unbounded.
        """
        result = await self.db.execute(
            select(OdometerRecord.odometer_km)
            .where(OdometerRecord.vin == vin)
            .order_by(
                OdometerRecord.date.desc(),
                OdometerRecord.odometer_km.desc(),
                OdometerRecord.id.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _current_usage(self, vin: str, axis: UsageAxis) -> Decimal | None:
        """The vehicle's current figure on `axis`: its latest odometer, or its highest hours."""
        if axis.is_hours:
            hours, _ = await latest_engine_hours_and_date(self.db, vin)
            return hours
        return await self._current_odometer(vin)

    async def _publish_usage(
        self,
        vin: str,
        when: dt.date,
        value: Decimal | None,
        source_type: str,
        source_id: int,
        axis: UsageAxis,
    ) -> None:
        """Publish one figure through its axis's one-door publisher."""
        if axis.is_hours:
            await publish_tire_hours(self.db, vin, when, value, source_type, source_id)
        else:
            await publish_tire_odometer(self.db, vin, when, value, source_type, source_id)

    async def _publish_event(
        self,
        vin: str,
        when: dt.date,
        source_type: str,
        source_id: int,
        *,
        odometer_km: Decimal | None,
        engine_hours: Decimal | None,
    ) -> None:
        """Publish an event's odometer and hour meter, each owning only its own row."""
        await publish_tire_odometer(self.db, vin, when, odometer_km, source_type, source_id)
        await publish_tire_hours(self.db, vin, when, engine_hours, source_type, source_id)

    async def request_distance_formatter(
        self, current_user: User | None, vin: str
    ) -> DistanceFormatter:
        """The distance formatter for this request's messages.

        The caller's units, or the instance default when there is no caller
        (auth mode none), through the one policy every request-driven surface
        uses, with the vehicle's own odometer unit on top (#172). Resolved
        once per request and passed down, never per tire. `vin` is required so
        no caller can forget the vehicle; an unknown VIN simply adds nothing.

        Public because the set fit in `tire_set_service` resolves the same
        formatter, the same reason `refuse_contradictions` and
        `open_period_ids` are public.
        """
        vehicle = await self.db.get(Vehicle, vin.upper().strip())
        context = await render_context_for_request(current_user, self.db, vehicle=vehicle)
        return distance_formatter(adapter_for(context.units, "distance"))

    async def request_axes(self, current_user: User | None, vin: str) -> VehicleAxes:
        """The axes this vehicle's tires run on, with distances in the caller's unit.

        Public for the set fit, like `refuse_contradictions`.
        """
        vin = vin.upper().strip()
        vehicle = await self.db.get(Vehicle, vin)
        format_distance = await self.request_distance_formatter(current_user, vin)
        return VehicleAxes.for_vehicle(
            vehicle.usage_unit if vehicle is not None else None,
            vehicle.secondary_usage_enabled if vehicle is not None else None,
            format_distance,
        )

    @staticmethod
    def _derived_installed_date(tire: Tire) -> dt.date | None:
        """The `mounted_on` of the earliest period THAT HAS ONE.

        Null when the earliest period is the migrated assumed one with an
        unknown start. Deliberately not `MIN(mounted_on)` over the non-null
        values only: that would skip the unknown and report a later REMOUNT
        date as the installation date, which reads as fact and is wrong.
        """
        periods = sorted(
            tire.mount_periods or [], key=lambda mp: (mp.mounted_on or dt.date.min, mp.id)
        )
        if not periods:
            return None
        return periods[0].mounted_on

    def _to_response(
        self,
        tire: Tire,
        axes: VehicleAxes,
        include_readings: bool = True,
        current_odometer: Decimal | None = None,
    ) -> TireResponse:
        readings = sorted(
            list(tire.readings or []),
            key=lambda r: r.recorded_at,
            reverse=True,
        )
        axis = axes.primary
        wear = project_wear(tire, current_odometer, readings, axis=axis)
        distance = distance_on_tire(tire, current_odometer, axis)
        below = bool(
            tire.tread_depth_mm is not None
            and tire.min_tread_mm is not None
            and tire.tread_depth_mm <= tire.min_tread_mm
        )
        payload = TireResponse.model_validate(tire)
        # Same wire names as before v3.3.0. A single-value result type would
        # have silently dropped `projected_wear_date`, which the tire card
        # renders beside the km figure.
        payload.projected_wear_date = wear.wear_date
        payload.wear_status = wear.status.value
        payload.distance_status = distance.status.value
        payload.usage_axis = axis.kind
        payload.usage_on_tire = distance.all_time_value
        payload.known_usage = distance.known_value
        payload.known_usage_since = distance.known_since
        payload.projected_usage_remaining = wear.km_remaining
        # The km names stay for existing readers, empty on the hours axis.
        on_distance = not axis.is_hours
        payload.projected_km_remaining = wear.km_remaining if on_distance else None
        payload.distance_km = distance.all_time_value if on_distance else None
        payload.known_distance_km = distance.known_value if on_distance else None
        payload.known_distance_since = distance.known_since if on_distance else None
        # Union, not `or`. These are blockers for two DIFFERENT figures:
        # `distance_status` is the tire's lifetime, `wear_status` is the
        # interval between the two readings. `or` masked the wear blockers
        # whenever any lifetime blocker existed, so a tire whose projection
        # was fine still reported a period to repair, and a tire whose
        # projection was blocked pointed at the wrong period. Deduplicated
        # and sorted so the field is stable across requests.
        payload.blocking_period_ids = sorted(
            {*distance.blocking_period_ids, *wear.blocking_period_ids}
        )
        payload.history_faults = [
            HistoryFaultResponse(
                period_id=fault.period_id,
                code=fault.code,
                counterpart_id=fault.counterpart_id,
                message=fault.message,
            )
            for fault in validate_period_history(
                tire.mount_periods or [], tire.readings or [], axes=axes.captured
            )
        ]
        payload.installed_date = self._derived_installed_date(tire)
        payload.below_threshold = below
        payload.mount_periods = [
            MountPeriodResponse.model_validate(period)
            for period in sorted(
                tire.mount_periods or [], key=lambda mp: (mp.mounted_on or dt.date.min, mp.id)
            )
        ]
        if include_readings:
            payload.readings = [TireReadingResponse.model_validate(r) for r in readings]
        else:
            payload.readings = []
        return payload

    async def list_tires(
        self, vin: str, current_user: User | None, include_retired: bool = False
    ) -> TireListResponse:
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        try:
            await get_vehicle_or_403(vin, current_user, self.db)
            axes = await self.request_axes(current_user, vin)
            query = select(Tire).where(Tire.vin == vin)
            if not include_retired:
                # A retired tire is history, not inventory. It still appears in
                # analytics -- its final distance and wear are the most
                # complete data the app will ever have about it -- but it does
                # not belong in the list of tires you can act on.
                query = query.where(Tire.retired_on.is_(None))
            result = await self.db.execute(
                query.options(selectinload(Tire.readings), selectinload(Tire.mount_periods))
                # Mounted tires first, then stored ones. `position` is
                # nullable now, and a bare ORDER BY sorts NULLs FIRST on
                # SQLite and LAST on PostgreSQL, so the two dialects would
                # disagree about the order of a user's own tire list.
                .order_by(Tire.position.is_(None), Tire.position)
            )
            tires = result.scalars().unique().all()
            current_odometer = await self._current_usage(vin, axes.primary)
            responses = [
                self._to_response(t, axes, current_odometer=current_odometer) for t in tires
            ]
            return TireListResponse(
                tires=responses,
                total=len(responses),
                usage_axis=axes.primary.kind,
                tracks_distance=axes.tracks("distance"),
                tracks_hours=axes.tracks("hours"),
            )
        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "DB error listing tires for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def create_tire(
        self, vin: str, data: TireCreate, current_user: User | None
    ) -> TireResponse:
        """Create a tire. It is NOT mounted anywhere until you mount it.

        This replaced `upsert_tire`, and the change is the release's breaking
        one. Before v3.3.0 a tire WAS a corner: `POST /api/tires` carried a
        `position` and upserted by `(vin, position)`, so there was no way to
        own a tire that was off the vehicle -- a seasonal set had to be deleted
        and re-entered every six months, taking its readings with it.

        A tire is now a thing you own. Mounting is a separate operation with
        its own conflict semantics (that corner may be occupied), which is why
        it cannot be folded back into a create.

        A stale client still sending `position` gets a 422 naming the field,
        because `TireBase` forbids extras (D13). Pydantic's default is to
        ignore unknown fields, which here would silently create a SECOND,
        unmounted tire rather than updating the one at that corner.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
            axes = await self.request_axes(current_user, vin)
            fields = data.model_dump(exclude={"vin"})
            fields["storage_location"] = normalise_storage_location(fields.get("storage_location"))
            tire = Tire(vin=vin, **fields)
            self.db.add(tire)
            await self.db.commit()
            # Re-query rather than refresh(attribute_names=["readings"]).
            # updated_at is server-side onupdate=func.now(), so the flush leaves
            # it expired even with expire_on_commit=False; a partial refresh left
            # TireResponse to lazy-load it and the update path raised
            # MissingGreenlet -> 500 after the write had already committed.
            result = await self.db.execute(
                select(Tire)
                .where(Tire.id == tire.id)
                .options(selectinload(Tire.readings), selectinload(Tire.mount_periods))
            )
            tire = result.scalar_one()
            return await self._reload_and_sync(tire.id, vin, axes)
        except HTTPException:
            raise
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "DB error upserting tire for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def mount_tire(
        self, vin: str, tire_id: int, data: TireMountRequest, current_user: User | None
    ) -> TireResponse:
        """Mount a tire at a position, opening a mount period.

        **This is the only writer of `tires.position`** (D14), together with
        `dismount_tire`. Both representations -- the tire's current position
        and the open period's position -- are written here or neither is, so
        they cannot drift. An earlier design let a period's position be edited
        directly, which let the tire card and the reading history disagree
        about which corner a tire was on.

        Nothing at the database level prevents two tires on one vehicle from
        each holding an open period at FL: `tire_mount_periods` has no `vin`,
        so the constraint cannot be written there. It is enforced here, under
        the VEHICLE write lock (`lock_vehicle_for_write`), and it has its own
        race test because no index will catch it.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        await lock_vehicle_for_write(self.db, vin)
        axes = await self.request_axes(current_user, vin)
        refuse_untracked(axes, odometers=(data.mounted_odometer_km,), hours=(data.mounted_hours,))
        tire = await self._get_tire_for_update(vin, tire_id)

        if tire.retired_on is not None:
            raise HTTPException(status_code=409, detail="This tire is retired.")
        before = fault_map(tire.mount_periods or [], tire.readings or [], axes=axes.captured)

        if tire.position is not None:
            raise HTTPException(
                status_code=409,
                detail=f"This tire is already mounted at {tire.position}. Dismount it first.",
            )

        occupant = (
            await self.db.execute(
                select(Tire).where(
                    Tire.vin == vin,
                    Tire.position == data.position,
                    Tire.id != tire.id,
                )
            )
        ).scalar_one_or_none()
        if occupant is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Another tire is already mounted at {data.position}.",
            )

        # Hoisted so the period and the odometer reading cannot land on
        # different dates when this runs across midnight.
        mounted_on = data.mounted_on or household_today()
        tire.position = data.position
        # Appended to the relationship rather than `db.add`ed, so the
        # collection the history validator reads is the resulting set; then
        # flushed so the period has the id its odometer marker needs.
        period = TireMountPeriod(
            tire_id=tire.id,
            position=data.position,
            mounted_on=mounted_on,
            mounted_odometer_km=data.mounted_odometer_km,
            mounted_hours=data.mounted_hours,
            is_assumed=False,
            notes=data.notes,
        )
        tire.mount_periods.append(period)
        await self.db.flush()
        self.refuse_contradictions(tire, before, {period.id}, axes)
        # Refreshed so the in-memory object carries the column's quantized
        # precision (`Numeric(10, 2)`) instead of whatever scale the
        # request's JSON happened to use. The append above means no later
        # eager reload in this request re-reads this row.
        await self.db.refresh(period)
        await self._publish_event(
            vin,
            mounted_on,
            ODOMETER_SOURCE_TIRE_MOUNT,
            period.id,
            odometer_km=data.mounted_odometer_km,
            engine_hours=data.mounted_hours,
        )
        await self.db.commit()
        # The reminder title names the position, so mounting changes it.
        return await self._reload_and_sync(tire.id, vin, axes)

    async def dismount_tire(
        self, vin: str, tire_id: int, data: TireDismountRequest, current_user: User | None
    ) -> TireResponse:
        """Take a tire off the vehicle, closing its open period."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        await lock_vehicle_for_write(self.db, vin)
        axes = await self.request_axes(current_user, vin)
        refuse_untracked(
            axes, odometers=(data.dismounted_odometer_km,), hours=(data.dismounted_hours,)
        )
        tire = await self._get_tire_for_update(vin, tire_id)
        before = fault_map(tire.mount_periods or [], tire.readings or [], axes=axes.captured)

        if tire.position is None:
            raise HTTPException(status_code=409, detail="This tire is not mounted.")

        open_period = (
            await self.db.execute(
                select(TireMountPeriod)
                .where(
                    TireMountPeriod.tire_id == tire.id,
                    TireMountPeriod.dismounted_on.is_(None),
                )
                .order_by(TireMountPeriod.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        dismounted_on = data.dismounted_on or household_today()
        tire.position = None
        # Three intents, two shapes: a key absent from the body leaves the
        # location alone, an empty string clears it, text sets it. The
        # Dismount dialog seeds the field from the tire and always sends it.
        if data.storage_location is not None:
            tire.storage_location = normalise_storage_location(data.storage_location)
        if open_period is not None:
            open_period.dismounted_on = dismounted_on
            open_period.dismounted_odometer_km = data.dismounted_odometer_km
            open_period.dismounted_hours = data.dismounted_hours
            if data.notes:
                open_period.notes = data.notes
        await self.db.flush()
        self.refuse_contradictions(tire, before, {open_period.id} if open_period else set(), axes)
        # Published even when there is no open period to close: the user still
        # read that number off the dashboard. Owned by the period when there is
        # one, so the editor can move it later; by the tire otherwise.
        if open_period is not None:
            await self._publish_event(
                vin,
                dismounted_on,
                ODOMETER_SOURCE_TIRE_DISMOUNT,
                open_period.id,
                odometer_km=data.dismounted_odometer_km,
                engine_hours=data.dismounted_hours,
            )
        else:
            await self._publish_event(
                vin,
                dismounted_on,
                ODOMETER_SOURCE_TIRE,
                tire.id,
                odometer_km=data.dismounted_odometer_km,
                engine_hours=data.dismounted_hours,
            )
        await self.db.commit()
        return await self._reload_response(tire.id, vin, axes)

    async def create_and_mount(
        self, vin: str, data: TireCreateAndMountRequest, current_user: User | None
    ) -> TireResponse:
        """Create a tire and mount it, atomically.

        The conflict semantics are the MOUNT's: if the corner is occupied the
        whole operation fails and no tire is created. Doing the two calls by
        hand and losing the second would leave an orphan tire behind.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        await lock_vehicle_for_write(self.db, vin)
        axes = await self.request_axes(current_user, vin)
        refuse_untracked(axes, odometers=(data.mounted_odometer_km,), hours=(data.mounted_hours,))

        occupant = (
            await self.db.execute(
                select(Tire).where(Tire.vin == vin, Tire.position == data.position)
            )
        ).scalar_one_or_none()
        if occupant is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Another tire is already mounted at {data.position}.",
            )

        fields = data.model_dump(
            exclude={"vin", "position", "mounted_on", "mounted_odometer_km", "mounted_hours"}
        )
        fields["storage_location"] = normalise_storage_location(fields.get("storage_location"))
        tire = Tire(
            vin=vin,
            position=data.position,
            # Loaded-and-empty from birth. After the flush below this is a
            # persistent object, and an unloaded lazy collection would try to
            # load on first touch, which an async session cannot do.
            mount_periods=[],
            readings=[],
            **fields,
        )
        self.db.add(tire)
        await self.db.flush()
        mounted_on = data.mounted_on or household_today()
        period = TireMountPeriod(
            tire_id=tire.id,
            position=data.position,
            mounted_on=mounted_on,
            mounted_odometer_km=data.mounted_odometer_km,
            mounted_hours=data.mounted_hours,
            is_assumed=False,
        )
        tire.mount_periods.append(period)
        await self.db.flush()
        self.refuse_contradictions(tire, {}, {period.id}, axes)
        # Refreshed so the in-memory object carries the column's quantized
        # precision (`Numeric(10, 2)`) instead of whatever scale the
        # request's JSON happened to use ("1000" vs "1000.00"). The append
        # above means no later eager reload in this request re-reads this
        # row, so an unrefreshed value would ride along into any distance
        # figure computed from this same object later in the same session.
        await self.db.refresh(period)
        await self._publish_event(
            vin,
            mounted_on,
            ODOMETER_SOURCE_TIRE_MOUNT,
            period.id,
            odometer_km=data.mounted_odometer_km,
            engine_hours=data.mounted_hours,
        )
        await self.db.commit()
        return await self._reload_and_sync(tire.id, vin, axes)

    async def rotate_tires(
        self, vin: str, data: TireRotationRequest, current_user: User | None
    ) -> TireListResponse:
        """Move several tires at once, in two phases.

        **Why two phases.** `uq_tires_vin_position` is an IMMEDIATE unique
        index on both dialects, so assigning one tire at a time fails the
        moment a destination is still occupied -- which for a rotation is
        always. An X-pattern swap collides on the very first move even though
        the requested FINAL arrangement is perfectly legal.

        So: clear every affected `tires.position` and close every affected
        period, FLUSH, then assign the new positions and open the new periods.
        Deferring the constraint is not an option; SQLite has no
        `DEFERRABLE INITIALLY DEFERRED`.

        All or nothing. A rotation that applied its valid moves and rejected
        the rest would leave the vehicle in an arrangement nobody asked for.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        await lock_vehicle_for_write(self.db, vin)
        axes = await self.request_axes(current_user, vin)
        refuse_untracked(axes, odometers=(data.odometer_km,), hours=(data.engine_hours,))

        moving_ids = [move.tire_id for move in data.moves]
        tires = {
            tire.id: tire
            for tire in (
                await self.db.execute(
                    select(Tire)
                    .where(Tire.id.in_(moving_ids), Tire.vin == vin)
                    .options(selectinload(Tire.readings), selectinload(Tire.mount_periods))
                )
            )
            .scalars()
            .all()
        }
        missing = [tid for tid in moving_ids if tid not in tires]
        if missing:
            raise HTTPException(status_code=404, detail=f"Tire(s) not found: {missing}")

        retired = sorted(tire_id for tire_id, tire in tires.items() if tire.retired_on is not None)
        if retired:
            raise HTTPException(status_code=409, detail=f"Tire(s) {retired} are retired.")
        befores = {
            tid: fault_map(t.mount_periods or [], t.readings or [], axes=axes.captured)
            for tid, t in tires.items()
        }
        open_before = {tid: self.open_period_ids(t) for tid, t in tires.items()}

        # A destination held by a tire that is NOT part of this rotation is a
        # conflict, not a swap. Checked before any write.
        targets = {move.position for move in data.moves}
        blockers = (
            (
                await self.db.execute(
                    select(Tire).where(
                        Tire.vin == vin,
                        Tire.position.in_(targets),
                        Tire.id.notin_(moving_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        if blockers:
            occupied = sorted(t.position for t in blockers if t.position)
            raise HTTPException(
                status_code=409,
                detail=f"Position(s) {occupied} are held by tires not in this rotation.",
            )

        when = data.rotated_on or household_today()
        await apply_mount_moves(
            self.db,
            vacate=[tires[tire_id] for tire_id in moving_ids],
            assign=[(tires[move.tire_id], move.position) for move in data.moves],
            when=when,
            odometer_km=data.odometer_km,
            engine_hours=data.engine_hours,
            notes=data.notes,
        )
        for tid, tire in tires.items():
            self.refuse_contradictions(
                tire, befores[tid], open_before[tid] | self.open_period_ids(tire), axes
            )

        # ONE reading however many tires moved: the odometer is a fact about
        # the vehicle, not about each corner. `min(moving_ids)` is only the
        # marker's id and nothing reads it back -- it is order-independent, so
        # a client that lists its moves differently produces the same note.
        await self._publish_event(
            vin,
            when,
            ODOMETER_SOURCE_ROTATION,
            min(moving_ids),
            odometer_km=data.odometer_km,
            engine_hours=data.engine_hours,
        )
        await self.db.commit()
        return await self.list_tires(vin, current_user)

    async def _get_tire_for_update(self, vin: str, tire_id: int) -> Tire:
        """Load a tire, scoped to its vehicle, or 404.

        Must run UNDER the vehicle write lock. It loads `readings` and
        `mount_periods` eagerly, and a tire loaded before the lock keeps its
        stale state in the identity map after the lock is acquired, which is
        the bug the LiveLink lock needed a re-read to fix. Every caller takes
        the lock first; `test_tire_concurrency.py` spies on that.
        """
        tire = (
            await self.db.execute(
                select(Tire)
                .where(Tire.id == tire_id, Tire.vin == vin)
                .options(selectinload(Tire.readings), selectinload(Tire.mount_periods))
            )
        ).scalar_one_or_none()
        if tire is None:
            raise HTTPException(status_code=404, detail="Tire not found")
        return tire

    @staticmethod
    def refuse_contradictions(
        tire: Tire, before: FaultMap, touched: set[int], axes: VehicleAxes
    ) -> None:
        """Second half of the writer sequence: capture, mutate, flush, VALIDATE, commit.

        Incremental, not whole-history: `before` is the fault map captured
        before this write mutated anything, and only a fault that is new, or
        one a period this write touched participates in, refuses it, unless
        the write strictly shrinks the set of fault keys (see
        `new_or_touched_faults` for what "new" and "strictly shrinks" mean). A
        legacy fault on some other period survives and stays flagged. Runs
        over the tire's resulting
        period list, which is why every writer appends new periods to
        `tire.mount_periods` rather than `db.add`ing them, and flushes first so
        they have ids. A refusal raises before the commit; the request's
        rollback discards what the flush wrote. Public because the set fit in
        `tire_set_service` runs the same sequence.

        `axes` checks every axis the vehicle tracks and renders the refusal in
        the caller's units. Required, so a new writer can't forget it.
        """
        after = fault_map(tire.mount_periods or [], tire.readings or [], axes=axes.captured)
        faults = new_or_touched_faults(before, after, touched)
        if faults:
            raise HTTPException(status_code=409, detail=faults[0].message)

    @staticmethod
    def open_period_ids(tire: Tire) -> set[int]:
        """Ids of the tire's periods with no dismount date.

        Rotation and set fit close these and open new ones, so the union of
        this before and after the moves is the set of periods the write touched.
        """
        return {p.id for p in tire.mount_periods or [] if p.dismounted_on is None}

    async def _reload_and_sync(self, tire_id: int, vin: str, axes: VehicleAxes) -> TireResponse:
        """Reload, run the low-tread reminder sync, and serialise.

        The sync has to happen on every path that can change a tire's tread or
        its mounted state, not only on the reading path. A tire entered with a
        tread already below its threshold is exactly the case a user needs
        warned about, and the previous `upsert_tire` did sync it -- so the
        create/mount split had to carry that behaviour across rather than drop
        it silently.
        """
        tire = (
            await self.db.execute(
                select(Tire)
                .where(Tire.id == tire_id)
                .options(selectinload(Tire.readings), selectinload(Tire.mount_periods))
            )
        ).scalar_one()
        await self._sync_low_tread_reminder(tire)
        return await self._reload_response(tire_id, vin, axes)

    async def _reload_response(self, tire_id: int, vin: str, axes: VehicleAxes) -> TireResponse:
        """Re-query and serialise.

        Re-queried rather than refreshed: `updated_at` is a server-side
        onupdate, so a flush leaves it expired even with
        expire_on_commit=False, and a partial refresh left TireResponse to
        lazy-load it -- MissingGreenlet, a 500 after the write had committed.
        """
        tire = (
            await self.db.execute(
                select(Tire)
                .where(Tire.id == tire_id)
                .options(selectinload(Tire.readings), selectinload(Tire.mount_periods))
            )
        ).scalar_one()
        return self._to_response(
            tire, axes, current_odometer=await self._current_usage(vin, axes.primary)
        )

    async def update_tire(
        self, vin: str, tire_id: int, data: TireUpdate, current_user: User | None
    ) -> TireResponse:
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
            axes = await self.request_axes(current_user, vin)
            result = await self.db.execute(
                select(Tire)
                .where(Tire.id == tire_id, Tire.vin == vin)
                .options(selectinload(Tire.readings), selectinload(Tire.mount_periods))
            )
            tire = result.scalar_one_or_none()
            if not tire:
                raise HTTPException(status_code=404, detail="Tire not found")
            fields = data.model_dump(exclude_unset=True)
            # `tires.set_id` carries no composite FK against the tire's vin, by
            # design (D6: a set is UX grouping no calculation depends on, so it
            # is not worth one). That makes this the ONLY thing standing between
            # a user and a tire filed under another vehicle's set, so it is
            # checked before the assignment rather than after.
            if fields.get("set_id") is not None:
                owner = (
                    await self.db.execute(
                        select(TireSet.id).where(TireSet.id == fields["set_id"], TireSet.vin == vin)
                    )
                ).scalar_one_or_none()
                if owner is None:
                    raise HTTPException(status_code=404, detail="Tire set not found")
            for key, value in fields.items():
                if key == "storage_location":
                    value = normalise_storage_location(value)
                setattr(tire, key, value)
            await self.db.commit()
            # Named, not a bare refresh: the only thing this call needs is
            # `updated_at`, the server-side onupdate the commit just produced
            # (expire_on_commit=False leaves everything else already
            # current). A bare `db.refresh(tire)` expires every attribute,
            # `readings`/`mount_periods` included, and this request still
            # needs both below -- under an async session an expired
            # relationship cannot lazy-load on a synchronous touch, it raises
            # MissingGreenlet instead.
            await self.db.refresh(tire, attribute_names=["updated_at"])
            await self._sync_low_tread_reminder(tire)
            # WITH the odometer. Without it every edit answered as though the
            # vehicle had never had a reading, so a PUT that only changed a
            # brand came back reporting the tire's distance as unknown. The
            # wrong figure never rendered because the client refetches, which
            # is exactly why it survived.
            return self._to_response(
                tire, axes, current_odometer=await self._current_usage(vin, axes.primary)
            )
        except HTTPException:
            raise
        except OperationalError as e:
            await self.db.rollback()
            logger.error("DB error updating tire %s: %s", tire_id, sanitize_for_log(e))
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def retire_tire(
        self, vin: str, tire_id: int, data: TireDismountRequest, current_user: User | None
    ) -> TireResponse:
        """Retire a tire: it comes off the vehicle and keeps everything.

        This is what a user means by "I replaced this tire", and before v3.3.0
        the only way to express it was DELETE -- which cascades through every
        reading and every mount period. Shipping the mount-period model beside
        an unchanged delete would mean the first thing someone does after
        collecting a season of data is erase it.

        Delete still exists, for a tire entered by mistake.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        await lock_vehicle_for_write(self.db, vin)
        axes = await self.request_axes(current_user, vin)
        refuse_untracked(
            axes, odometers=(data.dismounted_odometer_km,), hours=(data.dismounted_hours,)
        )
        tire = await self._get_tire_for_update(vin, tire_id)
        before = fault_map(tire.mount_periods or [], tire.readings or [], axes=axes.captured)

        if tire.retired_on is not None:
            raise HTTPException(status_code=409, detail="This tire is already retired.")

        # One date for the closed period and the retirement both, so a retire
        # that runs across midnight cannot record two.
        retired_on = data.dismounted_on or household_today()
        # An open period's missing dismount is skipped: retiring closes it on retired_on.
        last_day = last_known_day(tire.mount_periods or [])
        if last_day is not None and last_day > retired_on:
            raise HTTPException(status_code=409, detail=retired_before_history(last_day))

        closed_period: TireMountPeriod | None = None
        if tire.position is not None:
            # Close the open period and free the corner, so the replacement can
            # go where the old one was.
            open_period = (
                await self.db.execute(
                    select(TireMountPeriod)
                    .where(
                        TireMountPeriod.tire_id == tire.id,
                        TireMountPeriod.dismounted_on.is_(None),
                    )
                    .order_by(TireMountPeriod.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if open_period is not None:
                open_period.dismounted_on = retired_on
                open_period.dismounted_odometer_km = data.dismounted_odometer_km
                open_period.dismounted_hours = data.dismounted_hours
            closed_period = open_period
            tire.position = None

        tire.retired_on = retired_on
        # The same three intents as a dismount: an absent key leaves the
        # location alone, an empty string clears it, text sets it. The Retire
        # dialog renders no location field, so only the API sends one.
        if data.storage_location is not None:
            tire.storage_location = normalise_storage_location(data.storage_location)
        await self.db.flush()
        self.refuse_contradictions(
            tire, before, {closed_period.id} if closed_period else set(), axes
        )
        if closed_period is not None:
            await self._publish_event(
                vin,
                retired_on,
                ODOMETER_SOURCE_TIRE_DISMOUNT,
                closed_period.id,
                odometer_km=data.dismounted_odometer_km,
                engine_hours=data.dismounted_hours,
            )
        else:
            await self._publish_event(
                vin,
                retired_on,
                ODOMETER_SOURCE_TIRE,
                tire.id,
                odometer_km=data.dismounted_odometer_km,
                engine_hours=data.dismounted_hours,
            )
        await self.db.commit()
        return await self._reload_response(tire.id, vin, axes)

    async def create_mount_period(
        self, vin: str, tire_id: int, data: MountPeriodCreate, current_user: User | None
    ) -> TireResponse:
        """Record a closed period the tire spent on a corner in the past.

        For history the user never recorded at the time, such as the seasons a
        set was on the car before MyGarage. Under the vehicle write lock and
        judged like any other write, with only the new period touched, so it
        is refused when it contradicts the tire's existing periods or readings.
        It never changes where the tire is now, and it is allowed on a retired
        tire: that tire's history is still its history. It just can't end
        after the retirement.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        await lock_vehicle_for_write(self.db, vin)
        axes = await self.request_axes(current_user, vin)
        refuse_untracked(
            axes,
            odometers=(data.mounted_odometer_km, data.dismounted_odometer_km),
            hours=(data.mounted_hours, data.dismounted_hours),
        )
        tire = await self._get_tire_for_update(vin, tire_id)
        if tire.retired_on is not None and data.dismounted_on > tire.retired_on:
            raise HTTPException(status_code=409, detail=past_retirement(tire.retired_on))

        before = fault_map(tire.mount_periods or [], tire.readings or [], axes=axes.captured)
        period = TireMountPeriod(
            tire_id=tire.id,
            position=data.position,
            mounted_on=data.mounted_on,
            mounted_odometer_km=data.mounted_odometer_km,
            mounted_hours=data.mounted_hours,
            dismounted_on=data.dismounted_on,
            dismounted_odometer_km=data.dismounted_odometer_km,
            dismounted_hours=data.dismounted_hours,
            is_assumed=False,
            notes=data.notes,
        )
        tire.mount_periods.append(period)
        await self.db.flush()
        self.refuse_contradictions(tire, before, {period.id}, axes)
        # Refreshed for the same reason `mount_tire` refreshes its new period:
        # appended rather than `db.add`ed, so the reload below will not
        # re-read this row from the identity map, and the column's quantized
        # precision (`Numeric(10, 2)`) has to come from somewhere before the
        # response is built.
        await self.db.refresh(period)

        await self._publish_event(
            vin,
            data.mounted_on,
            ODOMETER_SOURCE_TIRE_MOUNT,
            period.id,
            odometer_km=data.mounted_odometer_km,
            engine_hours=data.mounted_hours,
        )
        await self._publish_event(
            vin,
            data.dismounted_on,
            ODOMETER_SOURCE_TIRE_DISMOUNT,
            period.id,
            odometer_km=data.dismounted_odometer_km,
            engine_hours=data.dismounted_hours,
        )
        await self.db.commit()
        return await self._reload_response(tire.id, vin, axes)

    async def update_mount_period(
        self,
        vin: str,
        tire_id: int,
        period_id: int,
        data: MountPeriodUpdate,
        current_user: User | None,
    ) -> TireResponse:
        """Correct one period's bounds or notes, under the vehicle write lock.

        This is the only repair path for a period born without an odometer,
        which since v3.3.0 is every tire added at a corner through the Add
        Tire form and every tire migrated by 097. Refusals are 409s with a
        sentence: an open period is closed by Dismount, not here; a closed
        period is never reopened, because the open period is the one whose
        corner `tires.position` holds and that pairing is written only by
        mount, dismount and rotate.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        await lock_vehicle_for_write(self.db, vin)
        axes = await self.request_axes(current_user, vin)
        fields = data.model_dump(exclude_unset=True)
        refuse_untracked(
            axes,
            odometers=(fields.get("mounted_odometer_km"), fields.get("dismounted_odometer_km")),
            hours=(fields.get("mounted_hours"), fields.get("dismounted_hours")),
        )
        tire = await self._get_tire_for_update(vin, tire_id)
        period = next((p for p in tire.mount_periods or [] if p.id == period_id), None)
        if period is None:
            raise HTTPException(status_code=404, detail="Mount period not found")

        before = fault_map(tire.mount_periods or [], tire.readings or [], axes=axes.captured)
        is_open = period.dismounted_on is None
        touches_dismount = (
            "dismounted_on" in fields
            or "dismounted_odometer_km" in fields
            or "dismounted_hours" in fields
        )
        if is_open and touches_dismount:
            raise HTTPException(
                status_code=409, detail="This period is still open. Close it with Dismount."
            )
        if not is_open and "dismounted_on" in fields and fields["dismounted_on"] is None:
            raise HTTPException(
                status_code=409,
                detail="A closed period cannot be reopened. Mount the tire again instead.",
            )

        # The pairs as persisted, so the published records move only when a
        # VALUE changed. The editor sends every rendered field, so "the key
        # was in the body" says nothing, and a notes-only save that republished
        # an unchanged mount odometer would put the period's figure back over
        # a value the user corrected on the owned record itself.
        old = {
            axis.kind: (
                (period.mounted_on, axis.mounted(period)),
                (period.dismounted_on, axis.dismounted(period)),
            )
            for axis in axes.captured
        }
        old_dates = (period.mounted_on, period.dismounted_on)
        for key, value in fields.items():
            setattr(period, key, value)
        # A user who supplies the mount date is asserting it. The observed
        # date stays as the record of what the migration knew.
        if fields.get("mounted_on") is not None and period.is_assumed:
            period.is_assumed = False
        # Judged only when a date changed, for the same reason as `old`: a
        # period already past the retirement from before G4-71 still takes a
        # notes fix.
        last_day = last_known_day([period])
        if (
            tire.retired_on is not None
            and (period.mounted_on, period.dismounted_on) != old_dates
            and last_day is not None
            and last_day > tire.retired_on
        ):
            raise HTTPException(status_code=409, detail=past_retirement(tire.retired_on))

        await self.db.flush()
        self.refuse_contradictions(tire, before, {period.id}, axes)

        # Captured axes only: a junk odometer on an hours vehicle must not grow a row.
        for axis in axes.captured:
            old_mount, old_dismount = old[axis.kind]
            if (period.mounted_on, axis.mounted(period)) != old_mount:
                await self._follow_period_event(
                    vin,
                    ODOMETER_SOURCE_TIRE_MOUNT,
                    period.id,
                    period.mounted_on,
                    axis.mounted(period),
                    axis,
                )
            if (period.dismounted_on, axis.dismounted(period)) != old_dismount:
                await self._follow_period_event(
                    vin,
                    ODOMETER_SOURCE_TIRE_DISMOUNT,
                    period.id,
                    period.dismounted_on,
                    axis.dismounted(period),
                    axis,
                )
        await self.db.commit()
        # `_reload_response`, not `_reload_and_sync`: a period edit changes no tread.
        return await self._reload_response(tire.id, vin, axes)

    async def _follow_period_event(
        self,
        vin: str,
        source_type: str,
        period_id: int,
        when: dt.date | None,
        value: Decimal | None,
        axis: UsageAxis,
    ) -> None:
        """Keep the vehicle odometer record a period event published in step.

        By OWNERSHIP: only a record carrying this period's own marker is ever
        moved or deleted. A service visit's, a fuel-up's or LiveLink's record,
        a manual one, a reading's, a legacy tire-marked record, a rotation's or
        a set fit's record: none of those is this event's to move. A record is
        published only when both the date and the odometer are known, because
        `odometer_records.date` is not nullable and "I know the odometer but
        not the day" is the common migrated-tire case.

        Both branches apply the same test on the target day as a new mount
        does (`publish_tire_odometer`). When this period owns NO record,
        publishing goes through `_publish_usage`: nothing when another
        record on the day reads at or above the figure, otherwise a new record.
        When it owns one and another record on the target day reads at or above
        the new figure, the owned record is deleted rather than moved there:
        the day already has a reading at least as high, and a period moving
        off its old day must not leave its record behind. When the target day
        holds only lower records but one of them has a newer id, the owned
        record is deleted and created again under the same marker rather than
        moved. Either leaves the right current reading, which is the day's
        highest whatever the ids (`odometer_service.latest_odometer_km_and_date`);
        created again, the record is also the newest row on its day, so a
        listing ordered by date, then id, shows the day's rows in the order
        they were last recorded. Otherwise the owned record is moved or
        updated in place. The other records on either day are never touched.

        Both the move and the delete are flushed before returning. Request
        sessions do not autoflush (`app/database.py`), and the dismount pair's
        follow runs next in the same save: its same-day lookup is by SQL, and
        an unflushed move or delete would still show it the mount record on
        its old day, where it could decide to publish nothing.

        Why: a stale synced record becomes the vehicle's latest reading and
        poisons every mileage reminder, which is the reason `delete_tire`
        cleans these up marker-exact.

        Per axis (#217): an hours row follows its period the way the odometer row does.
        """
        marker = auto_sync_marker(source_type, period_id)
        owned = await _owned_usage_record(self.db, vin, axis, marker)
        if when is not None and value is not None:
            if owned is not None:
                others = [
                    record
                    for record in await _same_day_usage(self.db, vin, axis, when)
                    if record.id != owned.id
                ]
                if any(not axis.below(_usage_value(r), value) for r in others) or any(
                    record.id > owned.id for record in others
                ):
                    # Deleted, then published afresh under the same marker:
                    # nothing when the day already reads at least as high,
                    # otherwise a new record, the day's highest reading and
                    # its newest row.
                    await self.db.delete(owned)
                    await self.db.flush()
                    await self._publish_usage(vin, when, value, source_type, period_id, axis)
                else:
                    _move_usage_record(owned, when, value)
                    await self.db.flush()
            else:
                await self._publish_usage(vin, when, value, source_type, period_id, axis)
        elif owned is not None:
            await self.db.delete(owned)
            await self.db.flush()

    async def restore_tire(self, vin: str, tire_id: int, current_user: User | None) -> TireResponse:
        """Un-retire a tire. It goes back to storage with its whole history.

        The way back from a mistaken Retire, and the reason `mount_tire` can
        refuse a retired tire without stranding one. Putting it back on a
        corner is a Mount like any other. Returns through the reminder sync:
        a restored tire below its minimum tread should get its warning back.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        await lock_vehicle_for_write(self.db, vin)
        axes = await self.request_axes(current_user, vin)
        tire = await self._get_tire_for_update(vin, tire_id)
        if tire.retired_on is None:
            raise HTTPException(status_code=409, detail="This tire is not retired.")
        tire.retired_on = None
        await self.db.commit()
        return await self._reload_and_sync(tire.id, vin, axes)

    async def delete_tire(self, vin: str, tire_id: int, current_user: User | None) -> None:
        """Permanently delete a tire and everything measured about it.

        For a tire entered by mistake. To replace a worn tire, RETIRE it: this
        cascades through `tire_readings` and `tire_mount_periods`.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        await lock_vehicle_for_write(self.db, vin)
        result = await self.db.execute(
            select(Tire)
            .where(Tire.id == tire_id, Tire.vin == vin)
            .options(selectinload(Tire.mount_periods))
        )
        tire = result.scalar_one_or_none()
        if not tire:
            raise HTTPException(status_code=404, detail="Tire not found")

        # Detach the reminders first, in the same transaction as the delete.
        # The composite FK `(tire_id, vin) -> tires(id, vin)` carries NO
        # ON DELETE action: a referential action applies to every column in the
        # FK, so SET NULL would try to null `vin` as well -- and `vin` is NOT
        # NULL, which makes SQLite reject the delete outright and retiring a
        # tire impossible. Measured. Nulling `tire_id` here keeps the reminder
        # as history and makes it inert: the sync never adopts a row whose
        # `tire_id` is null.
        await self.db.execute(
            update(Reminder)
            .where(Reminder.tire_id == tire_id, Reminder.vin == vin)
            .values(tire_id=None, source=None)
        )
        # The odometer readings this tire published. Nothing cascades them:
        # `odometer_records` carries a FK for fuel-sourced rows only. A tire
        # entered with a typo'd odometer and then deleted would otherwise leave
        # the typo behind as the vehicle's latest reading, where it poisons
        # every mileage reminder the vehicle has. Marker-exact, so a manual row
        # is never touched: the tire-level marker its readings carry, and the
        # per-period markers its mounts and dismounts carry. A tire event
        # never takes over another record (`publish_tire_odometer`), so a row
        # carrying one of these markers is one this tire created; the
        # exception is a tire-marked row written before v3.4.0, when a tire
        # publish could re-mark a same-day automatic record as its own.
        # Collected before the cascade removes the periods.
        markers = [auto_sync_marker(ODOMETER_SOURCE_TIRE, tire_id)]
        for period in tire.mount_periods or []:
            markers.append(auto_sync_marker(ODOMETER_SOURCE_TIRE_MOUNT, period.id))
            markers.append(auto_sync_marker(ODOMETER_SOURCE_TIRE_DISMOUNT, period.id))
        await self.db.execute(
            delete(OdometerRecord)
            .where(OdometerRecord.vin == vin)
            .where(OdometerRecord.notes.in_(markers))
        )
        # The hour meter rows carry the same markers (#217).
        await self.db.execute(
            delete(HoursRecord).where(HoursRecord.vin == vin).where(HoursRecord.notes.in_(markers))
        )
        await self.db.delete(tire)
        await self.db.commit()

    async def add_reading(
        self,
        vin: str,
        tire_id: int,
        data: TireReadingCreate,
        current_user: User | None,
    ) -> TireResponse:
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
            axes = await self.request_axes(current_user, vin)
            refuse_untracked(axes, odometers=(data.odometer_km,), hours=(data.engine_hours,))
            result = await self.db.execute(
                select(Tire)
                .where(Tire.id == tire_id, Tire.vin == vin)
                .options(selectinload(Tire.readings), selectinload(Tire.mount_periods))
            )
            tire = result.scalar_one_or_none()
            if not tire:
                raise HTTPException(status_code=404, detail="Tire not found")

            reading = TireReading(
                tire_id=tire.id,
                vin=vin,
                position=tire.position,
                recorded_at=data.recorded_at,
                odometer_km=data.odometer_km,
                engine_hours=data.engine_hours,
                tread_depth_mm=data.tread_depth_mm,
                pressure_kpa=data.pressure_kpa,
                notes=data.notes,
            )
            self.db.add(reading)
            # Only the newest observation defines current state. A backdated
            # backfill previously overwrote a worn tire's tread with an old
            # healthy value, recomputed below_threshold from it, and completed a
            # genuinely needed low-tread reminder.
            #
            # Deliberately NOT falling back to tire.updated_at when history is
            # empty: that column is onupdate=func.now(), so an unrelated edit
            # would bump it to today and silently refuse a reading dated
            # yesterday. The upsert-supplied tread carries no measurement date,
            # so the first dated reading wins. Closing that gap needs a
            # tread_measured_at column, which needs a migration.
            #
            # Each measurement is carried across only when the reading actually
            # supplies it. Tread used to be assigned unconditionally, which was
            # harmless only while the column was NOT NULL. Since 094 a
            # pressure-only reading (#152: a slow leak, no tread gauge) would
            # otherwise null the parent tire's tread, and an unknown tread is
            # not a measurement of a healthy one: `below_threshold` would drop
            # to False and `_sync_low_tread_reminder` would mark a live
            # low-tread reminder done. Logging a pressure would have silently
            # dismissed the warning that the tire is worn out.
            # Per measure, so a later pressure-only reading doesn't hold back a
            # tread, and the other way round. A same-day reading wins: it has the
            # highest id, so it's the newest by (recorded_at, id) too.
            for measure in MEASURES:
                value = getattr(data, measure)
                newest = _newest_with(tire.readings or [], measure)
                if value is not None and (newest is None or data.recorded_at >= newest.recorded_at):
                    setattr(tire, measure, value)
            # A reading's odometer is vehicle context by this schema's own
            # words, not an observation of the tire. Without publishing it the
            # five writers above make things WORSE for someone who only records
            # readings: mounting gives the open period an upper bound equal to
            # its own start, and the card reports a confident "0 km" instead of
            # admitting it does not know.
            await self._publish_event(
                vin,
                data.recorded_at,
                ODOMETER_SOURCE_TIRE,
                tire.id,
                odometer_km=data.odometer_km,
                engine_hours=data.engine_hours,
            )
            await self.db.commit()
            # Read back at the columns' scale, so the echo says 170.00 and not 170.
            await self.db.refresh(reading)
            await self.db.refresh(tire)
            result = await self.db.execute(
                select(Tire)
                .where(Tire.id == tire_id)
                .options(selectinload(Tire.readings), selectinload(Tire.mount_periods))
            )
            tire = result.scalar_one()
            return await self._reload_and_sync(tire.id, vin, axes)
        except HTTPException:
            raise
        except OperationalError as e:
            await self.db.rollback()
            logger.error("DB error adding tire reading %s: %s", tire_id, sanitize_for_log(e))
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def delete_reading(
        self, vin: str, tire_id: int, reading_id: int, current_user: User | None
    ) -> None:
        """Delete one reading, for one that shouldn't be there at all.

        A reading with a wrong value is corrected in place by `update_reading`;
        the writers that check the mount history name the reading either way.

        No vehicle write lock, for the reason `add_reading` takes none: it
        writes no position, retirement or period row, which is what the lock
        serialises. And a delete is safer still than an add: the history rules
        only compare periods against readings that exist, so removing a
        reading can remove a contradiction but never create one.

        Undoes what `add_reading` left behind, and only that: the tread and
        pressure it may have copied onto the tire, the vehicle odometer record
        it published, and, through the same reload-and-sync path, the
        low-tread reminder that copied tread may have raised.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
            axes = await self.request_axes(current_user, vin)
            tire = (
                await self.db.execute(
                    select(Tire)
                    .where(Tire.id == tire_id, Tire.vin == vin)
                    .options(selectinload(Tire.readings), selectinload(Tire.mount_periods))
                )
            ).scalar_one_or_none()
            if tire is None:
                raise HTTPException(status_code=404, detail="Tire not found")
            # Looked up inside THIS tire's readings, so a reading id belonging
            # to another tire or another vehicle is a 404, never a delete.
            reading = next((r for r in tire.readings or [] if r.id == reading_id), None)
            if reading is None:
                raise HTTPException(status_code=404, detail="Reading not found")

            remaining = sorted(
                (r for r in tire.readings or [] if r.id != reading.id),
                key=lambda r: (r.recorded_at, r.id),
                reverse=True,
            )
            # The tire's tread and pressure, one measure at a time. `add_reading`
            # copies a reading's value onto the tire only when that reading is
            # the newest, and Add Tire and Edit set the tire's value with no
            # reading at all. So the value is the deleted reading's only while
            # the tire still holds exactly that value; then it falls back to
            # the newest remaining reading that measures it. When none does,
            # null: the only dated measurement on file was the one being
            # withdrawn, and an Add Tire value it replaced carries no date that
            # would make it true now. An unknown tread is what
            # `_sync_low_tread_reminder` treats as unknown, never as healthy.
            # A value that differs was set by the user or by a newer reading,
            # and is left alone.
            if _same_measure(tire.tread_depth_mm, reading.tread_depth_mm):
                tire.tread_depth_mm = next(
                    (r.tread_depth_mm for r in remaining if r.tread_depth_mm is not None), None
                )
            if _same_measure(tire.pressure_kpa, reading.pressure_kpa):
                tire.pressure_kpa = next(
                    (r.pressure_kpa for r in remaining if r.pressure_kpa is not None), None
                )

            # Each captured axis published its own row; a junk odometer on an hours vehicle stays put.
            for axis in axes.captured:
                await self._withdraw_reading_usage(
                    vin,
                    tire.id,
                    reading.id,
                    reading.recorded_at,
                    axis.reading(reading),
                    remaining,
                    axis,
                )

            # Removed from the loaded collection, not just `db.delete`d: the
            # reload below finds this tire in the identity map with `readings`
            # already loaded, and would otherwise hand the reminder sync a
            # collection that still holds the deleted row. `delete-orphan`
            # issues the DELETE on commit.
            tire.readings.remove(reading)
            await self.db.commit()
            # The response is discarded: the route answers 204, and the sync is
            # the point. It completes a low-tread reminder once the tire's
            # tread is measured healthy again, and leaves one pending when the
            # tread is still low or now unknown.
            await self._reload_and_sync(tire.id, vin, axes)
        except HTTPException:
            raise
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "DB error deleting tire reading %s of tire %s: %s",
                sanitize_for_log(reading_id),
                sanitize_for_log(tire_id),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def update_reading(
        self,
        vin: str,
        tire_id: int,
        reading_id: int,
        data: TireReadingUpdate,
        current_user: User | None,
    ) -> TireResponse:
        """Correct one reading in place: its date, measurements, figures or notes (#225).

        Under the vehicle write lock, like the period editor. The tire's tread and
        pressure, the rows the reading published on each axis the vehicle tracks,
        and the low-tread reminder follow the corrected values. A change that makes
        a mount period newly contradict the reading is a 409; one it already
        contradicted never blocks it.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db, require_write=True)
        await lock_vehicle_for_write(self.db, vin)
        axes = await self.request_axes(current_user, vin)
        fields = data.model_dump(exclude_unset=True)
        # The body's figures only: a junk figure already on the reading can't block an edit.
        refuse_untracked(
            axes, odometers=(fields.get("odometer_km"),), hours=(fields.get("engine_hours"),)
        )
        tire = await self._get_tire_for_update(vin, tire_id)
        # Looked up inside this tire's readings, so another tire's reading is a 404.
        reading = next((r for r in tire.readings or [] if r.id == reading_id), None)
        if reading is None:
            raise HTTPException(status_code=404, detail="Reading not found")
        if all(fields.get(m, getattr(reading, m)) is None for m in MEASURES):
            raise HTTPException(status_code=422, detail=MEASURES_NOTHING)

        readings = list(tire.readings or [])
        newest_before = {m: _newest_value(readings, m) for m in MEASURES}
        old_values = {m: getattr(reading, m) for m in MEASURES}
        old_day = reading.recorded_at
        published = {axis.kind: axis.reading(reading) for axis in axes.captured}
        periods = list(tire.mount_periods or [])
        contradicted = {
            (axis.kind, period.id)
            for axis, period in reading_contradictions(periods, reading, axes.captured)
        }

        for key, value in fields.items():
            setattr(reading, key, value)
        await self.db.flush()

        # Rule 5 flags each period once, so a period another reading already
        # contradicts would hide a new one. This judges the reading's own pairs.
        fresh = [
            (axis, period)
            for axis, period in reading_contradictions(periods, reading, axes.captured)
            if (axis.kind, period.id) not in contradicted
        ]
        if fresh:
            axis, period = fresh[0]
            raise HTTPException(
                status_code=409, detail=reading_contradiction_message(period, reading, axis)
            )

        moved = reading.recorded_at != old_day
        for m in MEASURES:
            value = getattr(reading, m)
            if _same_measure(getattr(tire, m), newest_before[m]):
                # It tracked the newest reading, so it tracks the newest one now.
                setattr(tire, m, _newest_value(readings, m))
            elif (
                value is not None
                and (moved or not _same_measure(value, old_values[m]))
                and _newest_with(readings, m) is reading
            ):
                # A value set by hand gives way only to a changed reading that's
                # now the newest, as logging it fresh would.
                setattr(tire, m, value)

        # Each captured axis moves its row only when its figure or the date changed;
        # an untracked axis's junk stays put, as `delete_reading` leaves it.
        others = [r for r in readings if r.id != reading.id]
        for axis in axes.captured:
            was, now = published[axis.kind], axis.reading(reading)
            if (old_day, was) == (reading.recorded_at, now):
                continue
            await self._withdraw_reading_usage(vin, tire.id, reading.id, old_day, was, others, axis)
            await self._publish_usage(
                vin, reading.recorded_at, now, ODOMETER_SOURCE_TIRE, tire.id, axis
            )

        await self.db.commit()
        # Read back at the columns' scale, so the echo says 170.00 and not 170.
        # Tire.readings cascades refresh, so this reloads the reading too.
        await self.db.refresh(tire)
        return await self._reload_and_sync(tire.id, vin, axes)

    async def _withdraw_reading_usage(
        self,
        vin: str,
        tire_id: int,
        reading_id: int,
        day: dt.date,
        value: Decimal | None,
        remaining: Sequence[TireReading],
        axis: UsageAxis,
    ) -> None:
        """Withdraw the row a reading published on `day` at `value`, if it is still that.

        `add_reading` publishes with `ODOMETER_SOURCE_TIRE` keyed by the TIRE,
        so the marker alone does not say which reading a record came from: a
        reading creates the tire's record only when no record on its day reads
        at or above it, and a later, higher reading of the same tire on that
        day raises it in place (a lower one leaves it). A record is this
        reading's only when it carries this tire's marker, sits on the
        reading's date, still holds the reading's odometer, and no remaining
        reading of this tire has that same date and
        odometer to keep it true. Anything else (a manual row, another tire's,
        a rotation's or a service visit's record, a legacy row another tire
        had taken over, a row on another day) is left alone, and nothing is
        done when no such record exists. At most one record goes.

        That one row is also the day's record for every OTHER reading logged
        on that day: a Log Reading session for four tires leaves one record,
        carrying the first tire's marker, that all four stand behind, because
        the other three found that record at their own kilometres and
        published nothing.
        Removing it alone would drop the vehicle's latest odometer back to an
        older day and make every mounted tire's distance confidently too low.
        So when a record is deleted, the highest remaining reading of this
        VEHICLE on that date on this axis (the newest on a tie) is published
        again, under its own tire's marker, so the day never reads below a
        reading still on file (#224); a lower same-day reading of the same
        tire is covered the same way. The delete is flushed first: request
        sessions do not autoflush, and the publish looks for a same-day row by
        SQL, where an unflushed delete would still show it this one.

        Takes the day and figure rather than the reading, so an edit can
        withdraw what it published after the reading changed.

        Per axis (#217).
        """
        if value is None:
            return
        if any(r.recorded_at == day and _same_measure(axis.reading(r), value) for r in remaining):
            return
        marker = auto_sync_marker(ODOMETER_SOURCE_TIRE, tire_id)
        candidates = [
            r for r in await _same_day_usage(self.db, vin, axis, day) if r.notes == marker
        ]
        # Compared in Python, as Decimals: NUMERIC equality in SQL depends on the dialect.
        record = next((c for c in candidates if _same_measure(_usage_value(c), value)), None)
        if record is None:
            return
        await self.db.delete(record)
        await self.db.flush()
        column = TireReading.engine_hours if axis.is_hours else TireReading.odometer_km
        # The reading is still in the database here (a delete goes on the
        # caller's commit, an edit only moved it), hence the id filter.
        backer = (
            await self.db.execute(
                select(TireReading)
                .where(
                    TireReading.vin == vin,
                    TireReading.recorded_at == day,
                    column.is_not(None),
                    TireReading.id != reading_id,
                )
                .order_by(column.desc(), TireReading.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if backer is not None:
            await self._publish_usage(
                vin,
                backer.recorded_at,
                axis.reading(backer),
                ODOMETER_SOURCE_TIRE,
                backer.tire_id,
                axis,
            )

    async def _sync_low_tread_reminder(self, tire: Tire) -> None:
        """Create or complete a pending 'Tire tread low (POS)' reminder.

        Hooks into the existing ``vehicle_reminders`` table so the calendar,
        notifications scheduler, and HA bridge all see low tread without a
        separate notification channel.
        """
        title = _low_tread_title(tire.position)
        # THREE states, not two. `not below` used to conflate "measured, and it
        # is fine" with "we do not know", which was safe only while a tread was
        # mandatory everywhere. It is not: `Tire.tread_depth_mm` has been
        # nullable since 085 (clear the field in the edit drawer and the upsert
        # writes an explicit null), and since 094 a reading may omit one too.
        # Only a MEASUREMENT above the threshold may complete a live safety
        # reminder; an unknown tread leaves it exactly as it was.
        #
        # `known` and `below` are derived in ONE branch rather than each
        # repeating the None checks: two copies of one predicate can drift
        # apart, and a `below` that outlives its `known` is precisely the defect
        # this code exists to prevent. A branch rather than
        # `known and tread <= limit` because pyright does not carry a
        # `is not None` narrowing through an intermediate flag.
        tread = tire.tread_depth_mm
        limit = tire.min_tread_mm
        if tread is None or limit is None:
            known = False
            below = False
        else:
            known = True
            below = tread <= limit
        # Identity is the TIRE, not the title. Titles are arbitrary user
        # input, so matching on one adopts a reminder a human wrote and
        # completes it on their behalf. `scalars().all()` rather than
        # `scalar_one_or_none()`: rows created before this fix can leave more
        # than one pending row per tire, and raising on that would make the
        # bug unfixable from inside the app.
        owned = (
            (
                await self.db.execute(
                    select(Reminder)
                    .where(
                        Reminder.tire_id == tire.id,
                        Reminder.source == "low_tread",
                        Reminder.status == "pending",
                    )
                    .order_by(Reminder.id)
                )
            )
            .scalars()
            .all()
        )
        existing = owned[0] if owned else None
        # A pre-fix row could have left more than one pending reminder on the
        # same tire (matched by title back then, not by identity). Collapse
        # every extra one now rather than leaving it to keep firing.
        dirty = False
        for duplicate in owned[1:]:
            duplicate.status = "done"
            dirty = True

        # C10 predates some rows still pending on an upgraded instance. A
        # reminder created by a pre-C10 release carries `reminder_type="both"`
        # with `due_mileage_km=None`, which `ReminderCreate` rejects -- so
        # this release's editability fix never reached an owner's EXISTING
        # low-tread reminder, only ones created from here on. Repaired
        # unconditionally, before the branches below, so it runs whichever
        # of them fires this sync, including the case where the tire is
        # still below threshold and nothing else about the row changes.
        #
        # The predicate is deliberately exact, not "anything not date-typed
        # with no mileage". A user can take this reminder and add a real
        # mileage target, which makes it `reminder_type="both"` with a
        # genuine `due_mileage_km` -- a valid, user-authored edit, not a
        # corrupt row. Matching on `reminder_type != "date"` alone would
        # revert that edit and null their mileage on the next sync, silently.
        # `both` with a NULL mileage is precisely what the pre-C10
        # constructor wrote and precisely what the write schema rejects; any
        # other combination is either already valid or was never ours to
        # begin with, and is left alone.
        if (
            existing is not None
            and existing.reminder_type == "both"
            and existing.due_mileage_km is None
        ):
            existing.reminder_type = "date"
            existing.due_mileage_km = None
            dirty = True

        if below and existing is None:
            due = household_today()
            # `project_wear` sorts its own readings now. The old call passed
            # them unsorted, so `newer` was the OLDEST reading, `tread_delta`
            # came out negative, and this projection has been silently absent
            # from every low-tread reminder ever raised.
            # Below the minimum the projection reads no distance, so no current figure is needed.
            wear = project_wear(tire, None)
            start_km, start_hours = await start_readings(self.db, tire.vin)
            reminder = Reminder(
                vin=tire.vin,
                # Which tire, and that WE made this. The sync never adopts a
                # row whose `source` or `tire_id` is null, so a reminder a
                # human wrote is left alone, and a reminder whose tire has
                # been deleted becomes inert rather than attaching itself to
                # the next tire at that corner.
                tire_id=tire.id,
                source="low_tread",
                tread_depth_mm=tire.tread_depth_mm,
                tread_threshold_mm=tire.min_tread_mm,
                title=title,
                # Always "date". `km_remaining` is a distance REMAINING, not
                # an absolute odometer target, so there is nothing to put in
                # `due_mileage_km` -- and `ReminderCreate` requires a mileage
                # for "both". The ORM insert bypasses that validator, so the
                # old row landed and then rejected every ordinary edit.
                reminder_type="date",
                due_date=wear.wear_date or due,
                due_mileage_km=None,
                status="pending",
                start_odometer_km=start_km,
                start_hours=start_hours,
            )
            self.db.add(reminder)
            dirty = True
        elif known and not below and existing is not None:
            existing.status = "done"
            dirty = True
        elif below and existing is not None:
            # A rotation or a dismount renames the corner, and a new reading moves the tread.
            if existing.title != title:
                existing.title = title
                dirty = True
            if not _same_measure(existing.tread_depth_mm, tire.tread_depth_mm):
                existing.tread_depth_mm = tire.tread_depth_mm
                dirty = True
            if not _same_measure(existing.tread_threshold_mm, tire.min_tread_mm):
                existing.tread_threshold_mm = tire.min_tread_mm
                dirty = True

        if dirty:
            await self.db.commit()

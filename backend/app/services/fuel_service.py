"""Fuel record business logic service layer with L/100km calculation.

Canonical units (since v2.26.2): SI metric. Fuel economy surfaces as
L/100 km (lower is better). Imperial display is done client-side via the
frontend UnitFormatter.
"""

# pyright: reportReturnType=false, reportOptionalOperand=false

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date as date_type
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AddressBookEntry
from app.models.fuel import FuelRecord
from app.models.user import User
from app.schemas.fuel import (
    READING_AND_AMOUNT_FIELDS,
    FuelRecordCreate,
    FuelRecordResponse,
    FuelRecordUpdate,
    check_reading_and_amount,
)
from app.utils.cache import cached, invalidate_cache_for_vehicle
from app.utils.def_sync import ensure_def_capable, sync_def_from_fuel_record
from app.utils.fuel_station_sync import resolve_fuel_station
from app.utils.hours_sync import sync_hours_from_record
from app.utils.logging_utils import sanitize_for_log
from app.utils.odometer_sync import remove_synced_odometer, sync_odometer_from_record

logger = logging.getLogger(__name__)


# Propane-by-weight → liters conversion factor.
# Derived from: gal = lb/4.24 (old imperial formula, 4.24 lb/gal density of propane)
#   L_per_kg = (1/0.45359237) / 4.24 * 3.785411784  ≈  1.96826 L/kg
# (a separately rounded figure; the stored constant below is unchanged)
PROPANE_LITERS_PER_KG = Decimal("1.9685")


async def resolve_station_names(
    db: AsyncSession, records: list[FuelRecord]
) -> dict[int, str | None]:
    """Map ``record.id`` -> the station name to display for that record.

    A record either links an address-book entry (FK, freetext nulled by
    ``resolve_fuel_station`` case 1) or carries a one-time-visit freetext name.
    Neither alone is a reliable display value, so callers get the resolved
    name: address-book ``business_name`` first, freetext as fallback.

    Address-book names are fetched in one batched query, so this stays O(1)
    queries regardless of how many records are passed (issue #108).
    """
    station_ids = {r.station_address_book_id for r in records if r.station_address_book_id}
    names: dict[int, str] = {}
    if station_ids:
        result = await db.execute(
            select(AddressBookEntry.id, AddressBookEntry.business_name).where(
                AddressBookEntry.id.in_(station_ids)
            )
        )
        names = dict(result.all())  # type: ignore[arg-type]

    # names has int keys, so a null FK simply misses and falls back to freetext.
    return {r.id: names.get(r.station_address_book_id) or r.station_name_freetext for r in records}


async def build_fuel_response(
    db: AsyncSession,
    record: FuelRecord,
    l_per_100km: Decimal | None,
    l_per_hr: Decimal | None = None,
) -> FuelRecordResponse:
    """Build the API response for a single fuel record, station name resolved.

    Uses ``db.get`` rather than the batched lookup: on create/update the
    address-book row is already in the session's identity map (the write path
    just loaded or created it), so this usually resolves without any query.

    ``l_per_hr`` is the hours-economy analog of ``l_per_100km`` (L/hr over the
    full-tank interval's Δengine_hours); ``None`` for pure-distance vehicles.
    """
    station_name = record.station_name_freetext
    if record.station_address_book_id:
        entry = await db.get(AddressBookEntry, record.station_address_book_id)
        station_name = (entry.business_name if entry else None) or record.station_name_freetext
    return _fuel_response(record, l_per_100km, l_per_hr, station_name)


def _fuel_response(
    record: FuelRecord,
    l_per_100km: Decimal | None,
    l_per_hr: Decimal | None,
    station_name: str | None,
) -> FuelRecordResponse:
    """Assemble a response from an ORM row plus its derived fields."""
    record_dict = record.__dict__.copy()
    record_dict["l_per_100km"] = l_per_100km
    record_dict["l_per_hr"] = l_per_hr
    record_dict["station_name"] = station_name
    return FuelRecordResponse(**record_dict)


def calculate_l_per_100km(
    current_record: FuelRecord,
    previous_record: FuelRecord | None,
    interval_liters: Decimal | None = None,
) -> Decimal | None:
    """Calculate L/100km for a full-tank fuel record.

    Logic:
    - Only calculate for full tank fill-ups
    - Skip if no previous full tank fill-up
    - Skip if no odometer recorded
    - L/100km = fuel_since_previous_full / (distance_km / 100)

    ``interval_liters`` is the total fuel added since the previous full tank —
    every partial fill-up in between PLUS this full fill-up. This is the
    correct numerator: the distance was covered on all that fuel, not just the
    volume of the final full fill-up. When the caller can't supply it we fall
    back to ``current_record.liters`` alone, which under-reports consumption
    whenever partial fill-ups exist (issue #113); callers on the display and
    average paths always pass it.

    Lower values are better fuel economy.
    """
    # Only calculate for full tank fill-ups
    if not current_record.is_full_tank:
        return None

    # A missed fill-up means the distance since the previous record includes
    # fuel that was never recorded — no valid economy figure exists for this
    # record. It still re-anchors the sequence for the NEXT fill-up.
    if current_record.missed_fillup:
        return None

    # Need odometer_km and liters on current record. A zero odometer counts as
    # missing: it is far more often a placeholder than a brand-new vehicle, and
    # anchoring on one would make the next real tank span the whole odometer.
    if not current_record.odometer_km or not current_record.liters:
        return None

    # Need a previous record to calculate distance
    if not previous_record or not previous_record.odometer_km:
        return None

    distance_km = current_record.odometer_km - previous_record.odometer_km

    # Sanity check
    if distance_km <= 0 or current_record.liters <= 0:
        return None

    liters = interval_liters if interval_liters is not None else current_record.liters
    if liters <= 0:
        return None

    l_per_100km = (liters / distance_km) * Decimal("100")
    return round(l_per_100km, 2)


def calculate_hours_economy(
    current_record: FuelRecord,
    previous_record: FuelRecord | None,
    interval_liters: Decimal,
    interval_cost: Decimal,
) -> tuple[Decimal | None, Decimal] | None:
    """L/hr + cost/hr for a full-tank record, over the engine-hours delta.

    The hours analog of :func:`calculate_l_per_100km`: same full-tank / missed /
    previous-endpoint guards, but the axis is ``engine_hours`` (dimensionless —
    no unit conversion) instead of ``odometer_km``, and it yields TWO figures
    from TWO interval numerators over the same Δhours:

    - ``interval_liters`` = every liter added since the previous full-tank
      endpoint (partials + this fill), so ``l_per_hr = interval_liters / Δhours``
      — UNLESS ``interval_liters <= 0``, in which case ``l_per_hr`` is
      ``None`` (P3 backlog fix): a zero-liters interval has no fuel-economy
      figure at all, and letting it compute to ``0.00`` would drag
      ``average_l_per_hr`` toward zero instead of being excluded from it.
    - ``interval_cost`` = every net cost since that endpoint, so
      ``cost_per_hr = interval_cost / Δhours`` — ALWAYS computed when the
      interval itself is valid (non-increasing-meter guards above still
      apply). Unlike liters, a zero/near-zero cost is a legitimate figure
      (e.g. a free top-off), so ``cost_per_hr`` is never suppressed for
      want of liters. ``cost`` is already net of any rebate (see
      :class:`~app.models.fuel.FuelRecord`), so no rebate math here.

    Because there are two numerators, this does NOT gate on either being
    present (unlike the distance calc's single ``liters`` guard): a valid
    interval always yields a ``cost_per_hr`` figure, and an ``l_per_hr``
    figure whenever ``interval_liters`` is positive — so a cost figure is
    never dropped for want of liters. The endpoint / missed / towing rules
    (every full tank is an endpoint, a missed fill re-anchors without a
    figure, a towing tank is tagged) live in
    :func:`hours_economy_periods` and match the distance calc
    exactly. Returns ``None`` (no figure at all) for a partial, a missed
    fill-up, a missing endpoint, or a non-increasing meter.
    """
    # Only full-tank endpoints score (defensive; the accumulator only calls
    # this at endpoints). Mirrors calculate_l_per_100km.
    if not current_record.is_full_tank:
        return None

    # A missed fill-up covers unmeasured fuel: no valid figure, but it still
    # re-anchors the next interval (handled by the caller).
    if current_record.missed_fillup:
        return None

    # Need this record's own hours reading and a previous endpoint to delta from.
    if current_record.engine_hours is None:
        return None
    if previous_record is None or previous_record.engine_hours is None:
        return None

    delta_hours = current_record.engine_hours - previous_record.engine_hours
    if delta_hours <= 0:
        return None

    l_per_hr = round(interval_liters / delta_hours, 2) if interval_liters > 0 else None
    cost_per_hr = round(interval_cost / delta_hours, 2)
    return l_per_hr, cost_per_hr


#: Realistic L/100km band (~5-100 MPG). A tank outside it is almost always a
#: data-entry slip (a mistyped odometer or volume). Averages leave it out, since
#: weighting by distance would let one slip swamp them; its own figure still
#: shows in the fuel list, where the slip can be seen and fixed.
MIN_REALISTIC_L_PER_100KM = Decimal("2.35")
MAX_REALISTIC_L_PER_100KM = Decimal("47")


@dataclass(frozen=True)
class EconomyPeriod:
    """One full tank: the fill-up that closed it, and what it burned over what.

    ``towing`` is set when the closing fill-up or any partial fill-up within the
    tank is marked towing: that fuel was burned towing, so the whole tank was.
    """

    record: FuelRecord
    liters: Decimal
    distance_km: Decimal
    l_per_100km: Decimal
    towing: bool

    @property
    def plausible(self) -> bool:
        """Whether the figure is inside the realistic band."""
        return MIN_REALISTIC_L_PER_100KM <= self.l_per_100km <= MAX_REALISTIC_L_PER_100KM


def economy_periods(records_asc: list[FuelRecord]) -> list[EconomyPeriod]:
    """Every full tank's economy, in a single O(n) pass.

    ``records_asc`` must be every odometer-bearing fill-up for the vehicle,
    ordered by odometer ascending. Consecutive full-tank endpoints tile the
    odometer axis, so a running accumulator collects the liters of every partial
    fill-up since the previous endpoint and folds them, plus the endpoint's own
    fill, into that tank's numerator (issue #113). This is the single source of
    truth for the per-record, vehicle-average, dashboard, analytics and widget
    surfaces so they can't drift apart.

    Every full tank is an endpoint, towing or not. A towing tank is TAGGED, never
    merged: when it stopped being an endpoint, its fuel and distance folded into
    the next tank and the "excluding towing" figure still carried the towing
    fuel (issue #181 follow-up). A missed fill-up (amount unknown) is still an
    endpoint: it anchors the next tank but yields no figure of its own.

    Returns one period per endpoint that produced a valid figure, in odometer
    order.
    """
    results: list[EconomyPeriod] = []
    prev_endpoint: FuelRecord | None = None
    liters_since = Decimal(0)  # fuel added strictly after prev_endpoint
    towing_since = False  # any fill-up since prev_endpoint marked towing

    for record in records_asc:
        if record.odometer_km is None:
            continue
        if record.liters is not None:
            liters_since += record.liters
        towing_since = towing_since or bool(record.is_hauling)

        if not record.is_full_tank:
            continue

        # `record` is an endpoint; its own liters are already in `liters_since`.
        value = calculate_l_per_100km(record, prev_endpoint, liters_since)
        if (
            value is not None
            and prev_endpoint is not None
            and prev_endpoint.odometer_km is not None
        ):
            results.append(
                EconomyPeriod(
                    record=record,
                    liters=liters_since,
                    distance_km=record.odometer_km - prev_endpoint.odometer_km,
                    l_per_100km=value,
                    towing=towing_since,
                )
            )

        prev_endpoint = record
        liters_since = Decimal(0)
        towing_since = False

    return results


def compute_full_tank_economy(
    records_asc: list[FuelRecord],
    exclude_hauling: bool = False,
) -> list[tuple[FuelRecord, Decimal]]:
    """``(record, l_per_100km)`` for each full tank, from :func:`economy_periods`.

    With ``exclude_hauling`` the towing tanks are left out; the others keep the
    figures they have either way.
    """
    return [
        (period.record, period.l_per_100km)
        for period in economy_periods(records_asc)
        if not (exclude_hauling and period.towing)
    ]


def average_l_per_100km(periods: Sequence[EconomyPeriod]) -> Decimal | None:
    """Total fuel over total distance across the plausible ``periods``.

    Not a mean of the per-tank figures, which would count a 100 km tank as much
    as a 400 km one. Tanks outside the realistic band are left out (see
    ``MIN_REALISTIC_L_PER_100KM``); None when none is left.
    """
    periods = [period for period in periods if period.plausible]
    if not periods:
        return None
    liters = sum((period.liters for period in periods), Decimal(0))
    distance_km = sum((period.distance_km for period in periods), Decimal(0))
    return round(liters / distance_km * Decimal(100), 2)


# A trailer has no odometer, so a bottle refill's consumption is volume over
# TIME. Months are how people quote propane use ("a bottle a month in winter"),
# and 365.25 / 12 keeps a 30-day gap and a 31-day gap comparable.
DAYS_PER_MONTH = Decimal("30.4375")


def is_bottle_refill(record: FuelRecord) -> bool:
    """Whether a fuel record is a propane bottle refill.

    The schema's ``is_tank_refill`` rule: propane with no ``liters`` and no
    ``kwh``. Propane alongside either is a propane-POWERED vehicle's fill-up
    and belongs to the distance economy. One spelling, shared with the
    analytics propane figures so the two surfaces cannot classify a record
    differently.
    """
    return (
        record.propane_liters is not None
        and record.propane_liters > 0
        and record.liters is None
        and record.kwh is None
    )


def propane_fills(records: Iterable[FuelRecord]) -> list[tuple[date_type, Decimal]]:
    """Bottle refills as ``(date, litres)``, oldest first."""
    fills = [
        (record.date, record.propane_liters)
        for record in records
        if is_bottle_refill(record) and record.propane_liters is not None
    ]
    fills.sort(key=lambda fill: fill[0])
    return fills


def propane_l_per_month(fills: Sequence[tuple[date_type, Decimal]]) -> Decimal | None:
    """Litres of propane per average month across ``fills`` (oldest first).

    The first refill only starts the clock: its litres were burned before the
    window, exactly like the first full tank of a distance economy. Everything
    put in afterwards is spread over the days from the first refill to the
    last, so a partial top-up counts by its volume rather than as a bottle.
    None with fewer than two refills, or when they all share a day.
    """
    if len(fills) < 2:
        return None
    span_days = (fills[-1][0] - fills[0][0]).days
    if span_days <= 0:
        return None
    liters = sum((liters for _, liters in fills[1:]), Decimal(0))
    return round(liters * DAYS_PER_MONTH / span_days, 2)


@dataclass(frozen=True)
class HoursEconomyPeriod:
    """One full tank on the engine-hours axis: the hours mirror of
    :class:`EconomyPeriod`. ``l_per_hr`` is None for a zero-liters tank, whose
    ``cost_per_hr`` still counts."""

    record: FuelRecord
    liters: Decimal
    cost: Decimal
    hours: Decimal
    l_per_hr: Decimal | None
    cost_per_hr: Decimal
    towing: bool


def hours_economy_periods(records_asc: list[FuelRecord]) -> list[HoursEconomyPeriod]:
    """Every full tank's L/hr + cost/hr, in a single O(n) pass.

    The engine-hours mirror of :func:`economy_periods`. ``records_asc`` must be
    every ``engine_hours``-bearing fill-up for the vehicle, ordered by
    ``engine_hours`` ascending. Consecutive full-tank endpoints tile the hours
    axis, so a running accumulator collects the liters AND the net cost of every
    partial fill-up since the previous endpoint and folds them, plus the
    endpoint's own fill, into that tank's two numerators (design-review finding
    R1-H5: cost/hr must accumulate all partials, not just the endpoint fill).

    Endpoint rules are IDENTICAL to the distance function:
    - Every full tank is an endpoint; a towing tank is tagged, never merged.
    - A missed fill-up is still an endpoint: it anchors the next tank but yields
      no figure of its own.
    - A fill-up with no ``engine_hours`` is off the hours axis and is skipped
      entirely (its fuel does not fold in), the analog of skipping
      ``odometer_km is None`` in the distance pass.
    - A zero-liters tank (P3 backlog fix) yields ``l_per_hr = None`` while
      ``cost_per_hr`` is still computed; see :func:`calculate_hours_economy`.
    """
    results: list[HoursEconomyPeriod] = []
    prev_endpoint: FuelRecord | None = None
    liters_since = Decimal(0)  # fuel added strictly after prev_endpoint
    cost_since = Decimal(0)  # net cost added strictly after prev_endpoint
    towing_since = False  # any fill-up since prev_endpoint marked towing

    for record in records_asc:
        if record.engine_hours is None:
            continue
        if record.liters is not None:
            liters_since += record.liters
        if record.cost is not None:
            cost_since += record.cost
        towing_since = towing_since or bool(record.is_hauling)

        if not record.is_full_tank:
            continue

        # `record` is an endpoint; its own liters/cost are already accumulated.
        figure = calculate_hours_economy(record, prev_endpoint, liters_since, cost_since)
        if (
            figure is not None
            and prev_endpoint is not None
            and prev_endpoint.engine_hours is not None
        ):
            results.append(
                HoursEconomyPeriod(
                    record=record,
                    liters=liters_since,
                    cost=cost_since,
                    hours=record.engine_hours - prev_endpoint.engine_hours,
                    l_per_hr=figure[0],
                    cost_per_hr=figure[1],
                    towing=towing_since,
                )
            )

        prev_endpoint = record
        liters_since = Decimal(0)
        cost_since = Decimal(0)
        towing_since = False

    return results


def compute_full_tank_hours_economy(
    records_asc: list[FuelRecord],
    exclude_hauling: bool = False,
) -> list[tuple[FuelRecord, Decimal | None, Decimal]]:
    """``(record, l_per_hr, cost_per_hr)`` for each full tank, from
    :func:`hours_economy_periods`. With ``exclude_hauling`` the towing tanks are
    left out; the others keep the figures they have either way.
    """
    return [
        (period.record, period.l_per_hr, period.cost_per_hr)
        for period in hours_economy_periods(records_asc)
        if not (exclude_hauling and period.towing)
    ]


def average_hours_economy(
    periods: Sequence[HoursEconomyPeriod],
) -> tuple[Decimal | None, Decimal | None]:
    """Total fuel and total cost over total hours across ``periods``.

    ``l_per_hr`` counts only the tanks that have one: a zero-liters tank's hours
    would otherwise drag it toward zero (P3 backlog fix). ``cost_per_hr`` counts
    every tank, since cost/hr is never suppressed for want of liters.
    """
    fuelled = [period for period in periods if period.l_per_hr is not None]
    average_l_per_hr = (
        round(
            sum((p.liters for p in fuelled), Decimal(0))
            / sum((p.hours for p in fuelled), Decimal(0)),
            2,
        )
        if fuelled
        else None
    )
    average_cost_per_hr = (
        round(
            sum((p.cost for p in periods), Decimal(0))
            / sum((p.hours for p in periods), Decimal(0)),
            2,
        )
        if periods
        else None
    )
    return average_l_per_hr, average_cost_per_hr


async def sum_liters_since_previous_full(
    db: AsyncSession,
    vin: str,
    previous_full: FuelRecord,
    current_record: FuelRecord,
) -> Decimal | None:
    """SQL sum of liters in the odometer window (prev_full, current].

    Single-record equivalent of the accumulator in
    :func:`economy_periods`, for the create/update/get paths where
    loading the whole sequence to score one record would be wasteful. The
    current record must already be persisted so it is counted (issue #113).
    """
    if previous_full.odometer_km is None or current_record.odometer_km is None:
        return None

    result = await db.execute(
        select(func.coalesce(func.sum(FuelRecord.liters), 0))
        .where(FuelRecord.vin == vin)
        .where(FuelRecord.liters.isnot(None))
        .where(FuelRecord.odometer_km > previous_full.odometer_km)
        .where(FuelRecord.odometer_km <= current_record.odometer_km)
    )
    total = result.scalar()
    return Decimal(str(total)) if total is not None else Decimal(0)


async def get_previous_full_tank(
    db: AsyncSession,
    vin: str,
    current_date: date_type,
    current_odometer_km: Decimal | None,
) -> FuelRecord | None:
    """Get the most recent previous full tank fill-up."""
    query = (
        select(FuelRecord)
        .where(FuelRecord.vin == vin)
        .where(FuelRecord.is_full_tank.is_(True))
        .where(FuelRecord.date < current_date)
    )

    if current_odometer_km:
        query = query.where(FuelRecord.odometer_km < current_odometer_km)

    query = query.order_by(FuelRecord.date.desc()).limit(1)

    result = await db.execute(query)
    return result.scalar_one_or_none()


@cached(ttl_seconds=300)  # Cache for 5 minutes
async def calculate_average_l_per_100km(
    db: AsyncSession, vin: str, exclude_hauling: bool = True
) -> Decimal | None:
    """Calculate average L/100km across all full-tank fuel records.

    Args:
        db: Database session
        vin: Vehicle VIN
        exclude_hauling: If True (default), leave out towing tanks for more
            representative daily-driving economy

    Total fuel over total distance, per :func:`average_l_per_100km`.
    """
    # Load ALL fill-ups with an odometer (not just full tanks) so partial
    # fill-ups between two full tanks contribute their volume to the interval
    # (issue #113). Ordered by odometer so the accumulator is monotonic.
    result = await db.execute(
        select(FuelRecord)
        .where(FuelRecord.vin == vin)
        .where(FuelRecord.odometer_km.isnot(None))
        .order_by(FuelRecord.odometer_km.asc(), FuelRecord.date.asc(), FuelRecord.id.asc())
    )
    all_records = list(result.scalars().all())

    periods = economy_periods(all_records)
    if exclude_hauling:
        periods = [period for period in periods if not period.towing]
    return average_l_per_100km(periods)


@cached(ttl_seconds=300)  # Cache for 5 minutes
async def calculate_average_hours_economy(
    db: AsyncSession, vin: str, exclude_hauling: bool = True
) -> tuple[Decimal | None, Decimal | None]:
    """Average L/hr and cost/hr across all full-tank fuel records.

    Mirrors :func:`calculate_average_l_per_100km` so the hours and distance
    averages stay parallel: load every ``engine_hours``-bearing fill-up ordered
    by ``engine_hours`` ascending (partials contribute their liters and cost to
    the tank), score them once via :func:`hours_economy_periods`, then take each
    figure as total over total hours (:func:`average_hours_economy`).

    Args:
        db: Database session
        vin: Vehicle VIN
        exclude_hauling: If True (default), leave out towing tanks for more
            representative daily-use economy.

    Returns ``(average_l_per_hr, average_cost_per_hr)``. ``average_l_per_hr``
    is ``None`` when no full tank produced an ``l_per_hr`` figure (e.g. a
    pure-distance vehicle, OR every tank was zero-liters — P3 backlog fix: a
    zero-liters tank's hours are left out of it, so they can't drag it toward
    zero). ``average_cost_per_hr`` counts every tank (cost/hr is never
    suppressed for want of liters), so it can be non-``None`` even when
    ``average_l_per_hr`` is ``None``.
    """
    result = await db.execute(
        select(FuelRecord)
        .where(FuelRecord.vin == vin)
        .where(FuelRecord.engine_hours.isnot(None))
        .order_by(FuelRecord.engine_hours.asc(), FuelRecord.date.asc(), FuelRecord.id.asc())
    )
    all_records = list(result.scalars().all())

    periods = hours_economy_periods(all_records)
    if exclude_hauling:
        periods = [period for period in periods if not period.towing]
    return average_hours_economy(periods)


class FuelRecordService:
    """Service for managing fuel record business logic with L/100km calculations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _economy_for(self, vin: str, record: FuelRecord) -> Decimal | None:
        """L/100km for a single just-written/read full-tank record.

        Finds the previous full tank and sums the partial fill-ups since it
        (issue #113) via a bounded SQL query rather than loading the whole
        sequence. Returns None for partial fill-ups and un-anchorable records.
        """
        if not record.is_full_tank:
            return None
        prev_record = await get_previous_full_tank(self.db, vin, record.date, record.odometer_km)
        interval_liters = (
            await sum_liters_since_previous_full(self.db, vin, prev_record, record)
            if prev_record
            else None
        )
        return calculate_l_per_100km(record, prev_record, interval_liters)

    async def _hours_economy_for(self, vin: str, record: FuelRecord) -> Decimal | None:
        """L/hr for a single just-written/read full-tank record.

        Scores the record through the same O(n) accumulator the list and
        average paths use (``compute_full_tank_hours_economy`` — the single
        source of truth) so the per-record figure can't drift from the
        vehicle average. Only ``l_per_hr`` surfaces per record (cost/hr is an
        aggregate-only figure). Returns None for partial fill-ups, records with
        no ``engine_hours``, and un-anchorable records.
        """
        if record.engine_hours is None or not record.is_full_tank:
            return None
        result = await self.db.execute(
            select(FuelRecord)
            .where(FuelRecord.vin == vin)
            .where(FuelRecord.engine_hours.isnot(None))
            .order_by(FuelRecord.engine_hours.asc(), FuelRecord.date.asc(), FuelRecord.id.asc())
        )
        all_asc = list(result.scalars().all())
        for scored, l_per_hr, _cost_per_hr in compute_full_tank_hours_economy(all_asc):
            if scored.id == record.id:
                return l_per_hr
        return None

    async def list_fuel_records(
        self,
        vin: str,
        current_user: User | None,
        skip: int = 0,
        limit: int = 100,
        include_hauling: bool = False,
    ) -> tuple[list[FuelRecordResponse], int, Decimal | None, Decimal | None, Decimal | None]:
        """List fuel records with per-record economy + vehicle-wide averages.

        Returns ``(responses, total, average_l_per_100km, average_l_per_hr,
        average_cost_per_hr)``. The hours averages are ``None`` for a
        pure-distance vehicle, mirroring how the distance average is ``None``
        for a pure-hours one.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            _ = await get_vehicle_or_403(vin, current_user, self.db)

            result = await self.db.execute(
                select(FuelRecord)
                .where(FuelRecord.vin == vin)
                .order_by(FuelRecord.date.desc())
                .offset(skip)
                .limit(limit)
            )
            records = result.scalars().all()

            # Per-record economy for every full tank, computed once over the
            # whole ordered sequence so partial fill-ups fold into the next full
            # tank (issue #113). Towing tanks keep their figures here: the
            # per-record display shows one for each full fill-up.
            all_asc_result = await self.db.execute(
                select(FuelRecord)
                .where(FuelRecord.vin == vin)
                .where(FuelRecord.odometer_km.isnot(None))
                .order_by(FuelRecord.odometer_km.asc(), FuelRecord.date.asc(), FuelRecord.id.asc())
            )
            all_asc = list(all_asc_result.scalars().all())
            economy_by_id = {r.id: value for r, value in compute_full_tank_economy(all_asc)}

            # Per-record hours economy, computed the same way over the hours
            # axis (ordered by engine_hours) so both dimensions stay parallel.
            hours_asc_result = await self.db.execute(
                select(FuelRecord)
                .where(FuelRecord.vin == vin)
                .where(FuelRecord.engine_hours.isnot(None))
                .order_by(FuelRecord.engine_hours.asc(), FuelRecord.date.asc(), FuelRecord.id.asc())
            )
            hours_asc = list(hours_asc_result.scalars().all())
            hours_economy_by_id = {
                r.id: l_per_hr for r, l_per_hr, _ in compute_full_tank_hours_economy(hours_asc)
            }

            station_names = await resolve_station_names(self.db, list(records))
            responses = [
                _fuel_response(
                    record,
                    economy_by_id.get(record.id),
                    hours_economy_by_id.get(record.id),
                    station_names.get(record.id),
                )
                for record in records
            ]

            count_result = await self.db.execute(
                select(func.count()).select_from(FuelRecord).where(FuelRecord.vin == vin)
            )
            total = count_result.scalar()

            avg_value = await calculate_average_l_per_100km(
                self.db, vin, exclude_hauling=not include_hauling
            )
            avg_l_per_hr, avg_cost_per_hr = await calculate_average_hours_economy(
                self.db, vin, exclude_hauling=not include_hauling
            )

            return responses, total, avg_value, avg_l_per_hr, avg_cost_per_hr

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error listing fuel records for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def get_fuel_record(
        self, vin: str, record_id: int, current_user: User | None
    ) -> tuple[FuelRecord, Decimal | None, Decimal | None]:
        """Get a specific fuel record with L/100km and L/hr."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db)

        result = await self.db.execute(
            select(FuelRecord).where(FuelRecord.id == record_id).where(FuelRecord.vin == vin)
        )
        record = result.scalar_one_or_none()

        if not record:
            raise HTTPException(status_code=404, detail=f"Fuel record {record_id} not found")

        value = await self._economy_for(vin, record)
        hours_value = await self._hours_economy_for(vin, record)

        return record, value, hours_value

    async def create_fuel_record(
        self, vin: str, record_data: FuelRecordCreate, current_user: User | None
    ) -> tuple[FuelRecord, Decimal | None, Decimal | None]:
        """Create a new fuel record with L/100km calc.

        Uses a single outer transaction (since v2.27.0) so station create,
        usage_count bump, fuel-record insert, odometer sync, and DEF sync
        either all succeed or all roll back together.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            vehicle = await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            record_dict = record_data.model_dump()
            record_dict["vin"] = vin

            # Pop DEF fill level before creating FuelRecord (not a fuel table column)
            def_fill_level = record_dict.pop("def_fill_level", None)
            # Gate BEFORE any DB insert/mutation so a rejected request leaves
            # no fuel record row behind (the bypass surface this closes).
            if def_fill_level is not None:
                ensure_def_capable(vehicle)
            # Pop the one_time_visit form-only flag — not a column on fuel_records
            one_time_visit = bool(record_dict.pop("one_time_visit", False))
            station_id_in = record_dict.pop("station_address_book_id", None)
            station_name_in = record_dict.pop("station_name_freetext", None)

            # Mirror filled_at into date when only filled_at was provided.
            if record_dict.get("filled_at") is not None and record_dict.get("date") is None:
                record_dict["date"] = record_dict["filled_at"].date()

            # Auto-calculate propane_liters if tank-by-weight data provided
            if (
                record_dict.get("tank_size_kg") is not None
                and record_dict.get("tank_quantity") is not None
                and record_dict.get("propane_liters") is None
            ):
                tank_kg = Decimal(str(record_dict["tank_size_kg"]))
                qty = Decimal(str(record_dict["tank_quantity"]))
                calculated = tank_kg * PROPANE_LITERS_PER_KG * qty
                record_dict["propane_liters"] = calculated.quantize(Decimal("0.001"))

            # ---- Single outer transaction begins ----
            # 1. Resolve station inputs (may create an address_book row).
            station_id, station_freetext = await resolve_fuel_station(
                self.db,
                station_address_book_id=station_id_in,
                station_name_freetext=station_name_in,
                one_time_visit=one_time_visit,
            )
            record_dict["station_address_book_id"] = station_id
            record_dict["station_name_freetext"] = station_freetext

            # 2. Insert fuel record.
            record = FuelRecord(**record_dict)
            self.db.add(record)
            await self.db.flush()  # populate record.id without committing

            # 3. Odometer sync (no internal commit).
            if record.date and record.odometer_km:
                try:
                    await sync_odometer_from_record(
                        db=self.db,
                        vin=vin,
                        date=record.date,
                        odometer_km=record.odometer_km,
                        source_type="fuel",
                        source_id=record.id,
                        commit=False,
                    )
                except Exception as e:
                    # Log but do NOT swallow — let the outer transaction roll
                    # back so we don't end up with a stranded fuel record
                    # that's missing its odometer entry.
                    logger.warning(
                        "Failed to auto-sync odometer for fuel record (rolling back): %s",
                        sanitize_for_log(e),
                    )
                    raise

            # 3b. Engine-hours sync (no internal commit). Located by source
            # identity; engine_hours=None is a no-op on create (nothing to
            # delete). Composed into the same outer transaction.
            if record.date:
                try:
                    await sync_hours_from_record(
                        db=self.db,
                        vin=vin,
                        date=record.date,
                        engine_hours=record.engine_hours,
                        source_type="fuel",
                        source_id=record.id,
                        commit=False,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to auto-sync engine hours for fuel record (rolling back): %s",
                        sanitize_for_log(e),
                    )
                    raise

            # 4. DEF sync (no internal commit).
            if def_fill_level is not None:
                try:
                    await sync_def_from_fuel_record(
                        db=self.db,
                        vin=vin,
                        date=record.date,
                        odometer_km=record.odometer_km,
                        fill_level=def_fill_level,
                        fuel_record_id=record.id,
                        commit=False,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to auto-sync DEF for fuel record (rolling back): %s",
                        sanitize_for_log(e),
                    )
                    raise

            # 5. Single commit closes the outer transaction.
            await self.db.commit()
            await self.db.refresh(record)

            value = await self._economy_for(vin, record)
            hours_value = await self._hours_economy_for(vin, record)

            logger.info(
                "Created fuel record %s for %s (L/100km: %s)",
                record.id,
                sanitize_for_log(vin),
                value,
            )

            await invalidate_cache_for_vehicle(vin)

            return record, value, hours_value

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation creating fuel record for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Duplicate or invalid fuel record")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error creating fuel record for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def update_fuel_record(
        self,
        vin: str,
        record_id: int,
        record_data: FuelRecordUpdate,
        current_user: User | None,
    ) -> tuple[FuelRecord, Decimal | None, Decimal | None]:
        """Update a fuel record; recompute L/100km."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            vehicle = await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(FuelRecord).where(FuelRecord.id == record_id).where(FuelRecord.vin == vin)
            )
            record = result.scalar_one_or_none()

            if not record:
                raise HTTPException(status_code=404, detail=f"Fuel record {record_id} not found")

            update_data = record_data.model_dump(exclude_unset=True)
            # An edit can't leave a fill-up create would refuse, e.g. an emptied
            # propane refill that no list shows any more. Only an edit that
            # CHANGES one of the rule's fields is held to it: the forms send them
            # all on every save, and a webhook or pre-rule fill-up that already
            # falls short must still take a station or notes edit.
            changes_the_rule = any(
                update_data[field] != getattr(record, field)
                for field in READING_AND_AMOUNT_FIELDS & record_data.model_fields_set
            )
            if changes_the_rule:
                merged = {
                    field: update_data.get(field, getattr(record, field))
                    for field in READING_AND_AMOUNT_FIELDS
                }
                try:
                    check_reading_and_amount(**merged)
                except ValueError as e:
                    raise HTTPException(status_code=422, detail=str(e))
            def_fill_level = update_data.pop("def_fill_level", None)
            def_fill_level_was_sent = "def_fill_level" in record_data.model_fields_set
            # Gate BEFORE any field mutation so a rejected request leaves the
            # existing fuel record untouched.
            if def_fill_level_was_sent and def_fill_level is not None:
                ensure_def_capable(vehicle)

            # Mirror filled_at into date when only filled_at was sent.
            if (
                "filled_at" in record_data.model_fields_set
                and update_data.get("filled_at") is not None
                and "date" not in record_data.model_fields_set
            ):
                update_data["date"] = update_data["filled_at"].date()

            # Auto-calculate propane_liters if tank-by-weight data provided/updated
            if (
                update_data.get("tank_size_kg") is not None
                and update_data.get("tank_quantity") is not None
                and update_data.get("propane_liters") is None
            ):
                tank_size = update_data.get("tank_size_kg", record.tank_size_kg)
                tank_qty = update_data.get("tank_quantity", record.tank_quantity)
                if tank_size is not None and tank_qty is not None:
                    calculated = (
                        Decimal(str(tank_size)) * PROPANE_LITERS_PER_KG * Decimal(str(tank_qty))
                    )
                    update_data["propane_liters"] = calculated.quantize(Decimal("0.001"))

            # Station inputs go through the same resolver as create, so an edit
            # can re-point or promote a station instead of raw-writing the
            # columns (issue #108).
            one_time_visit = update_data.pop("one_time_visit", None)
            if {"station_address_book_id", "station_name_freetext"} & record_data.model_fields_set:
                # Default each omitted field from the record: under
                # exclude_unset an absent key carries no intent, and reading it
                # as None would let a caller that sends one station field wipe
                # the other. Same pattern as the propane block above.
                new_id = update_data.get("station_address_book_id", record.station_address_book_id)
                new_text = (
                    update_data.get("station_name_freetext", record.station_name_freetext) or None
                )
                # Resolve only on a real change: the form posts these fields on
                # every save and the resolver bumps usage_count, which counts
                # fill-ups, not saves.
                if (new_id, new_text) != (
                    record.station_address_book_id,
                    record.station_name_freetext,
                ):
                    station_id, station_freetext = await resolve_fuel_station(
                        self.db,
                        station_address_book_id=new_id,
                        station_name_freetext=new_text,
                        # A record with freetext and no FK IS a one-time visit;
                        # default to preserving that so editing such a station
                        # doesn't promote a stop the user kept out of the book.
                        one_time_visit=(
                            bool(one_time_visit)
                            if one_time_visit is not None
                            else record.station_address_book_id is None
                            and record.station_name_freetext is not None
                        ),
                    )
                    update_data["station_address_book_id"] = station_id
                    update_data["station_name_freetext"] = station_freetext

            for field, value in update_data.items():
                setattr(record, field, value)

            # ---- Single outer transaction begins ----
            await self.db.flush()  # apply field changes inside the same tx

            if record.date and record.odometer_km:
                try:
                    await sync_odometer_from_record(
                        db=self.db,
                        vin=vin,
                        date=record.date,
                        odometer_km=record.odometer_km,
                        source_type="fuel",
                        source_id=record.id,
                        commit=False,
                        operation="update",
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to auto-sync odometer for fuel record %s (rolling back): %s",
                        sanitize_for_log(record_id),
                        sanitize_for_log(e),
                    )
                    raise
            elif "odometer_km" in record_data.model_fields_set and not record.odometer_km:
                # Cleared on edit (or set to 0, which a create never syncs): take
                # the reading it synced with it, the way the hours sync below
                # deletes its row.
                await remove_synced_odometer(self.db, vin, "fuel", record.id)

            # Engine-hours sync. Runs unconditionally (not gated on a non-null
            # reading) so clearing engine_hours to null deletes the synced row;
            # located by source identity, composed into the same transaction.
            if record.date:
                try:
                    await sync_hours_from_record(
                        db=self.db,
                        vin=vin,
                        date=record.date,
                        engine_hours=record.engine_hours,
                        source_type="fuel",
                        source_id=record.id,
                        commit=False,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to auto-sync engine hours for fuel record %s (rolling back): %s",
                        sanitize_for_log(record_id),
                        sanitize_for_log(e),
                    )
                    raise

            if def_fill_level_was_sent:
                try:
                    if def_fill_level is not None:
                        await sync_def_from_fuel_record(
                            db=self.db,
                            vin=vin,
                            date=record.date,
                            odometer_km=record.odometer_km,
                            fill_level=def_fill_level,
                            fuel_record_id=record.id,
                            commit=False,
                        )
                    else:
                        from app.models.def_record import DEFRecord

                        await self.db.execute(
                            delete(DEFRecord).where(DEFRecord.origin_fuel_record_id == record_id)
                        )
                except Exception as e:
                    logger.warning(
                        "Failed to auto-sync DEF for fuel record %s (rolling back): %s",
                        sanitize_for_log(record_id),
                        sanitize_for_log(e),
                    )
                    raise

            await self.db.commit()
            await self.db.refresh(record)

            value = await self._economy_for(vin, record)
            hours_value = await self._hours_economy_for(vin, record)

            logger.info(
                "Updated fuel record %s for %s", sanitize_for_log(record_id), sanitize_for_log(vin)
            )

            await invalidate_cache_for_vehicle(vin)

            return record, value, hours_value

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation updating fuel record %s for %s: %s",
                sanitize_for_log(record_id),
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Database constraint violation")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error updating fuel record %s for %s: %s",
                sanitize_for_log(record_id),
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def delete_fuel_record(self, vin: str, record_id: int, current_user: User | None) -> None:
        """Delete a fuel record and any linked DEF auto-synced record."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(FuelRecord).where(FuelRecord.id == record_id).where(FuelRecord.vin == vin)
            )
            record = result.scalar_one_or_none()

            if not record:
                raise HTTPException(status_code=404, detail=f"Fuel record {record_id} not found")

            from app.models.def_record import DEFRecord
            from app.models.odometer import OdometerRecord

            await self.db.execute(
                delete(DEFRecord).where(DEFRecord.origin_fuel_record_id == record_id)
            )
            # Clean up the synced odometer row. PG enforces this via the FK
            # ``fk_odometer_records_fuel_record`` (ON DELETE CASCADE) added
            # in migration 055, but SQLite doesn't enforce FKs without
            # PRAGMA foreign_keys=ON, so we sweep at the service layer too.
            # Issuing the delete on both engines is harmless (idempotent
            # on PG since the row is already gone by the time the cascade
            # fires below) and keeps a single code path.
            await self.db.execute(
                delete(OdometerRecord).where(OdometerRecord.fuel_record_id == record_id)
            )
            await self.db.execute(
                delete(FuelRecord).where(FuelRecord.id == record_id).where(FuelRecord.vin == vin)
            )
            await self.db.commit()

            logger.info(
                "Deleted fuel record %s for %s", sanitize_for_log(record_id), sanitize_for_log(vin)
            )

            await invalidate_cache_for_vehicle(vin)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation deleting fuel record %s for %s: %s",
                sanitize_for_log(record_id),
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Cannot delete record with dependent data")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error deleting fuel record %s for %s: %s",
                sanitize_for_log(record_id),
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")


# Back-compat aliases for v1 widget endpoints (kept until v3.2.0).
calculate_mpg = calculate_l_per_100km
calculate_average_mpg = calculate_average_l_per_100km

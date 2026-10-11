"""Refuse a tire history that contradicts itself, at write time.

The projection already knows the shapes that make a per-tire figure
meaningless: a period whose bounds run backwards, two periods claiming the
same kilometres, dates and odometers that describe two different histories.
It handles them by withholding the figure. This module applies the same
rules, plus one the projection never needed, BEFORE the write commits, so
the contradiction is refused with a sentence instead of stored and explained
later.

The extra rule is date overlap. The projection is odometer-based and never
needed it; an editor that lets a user type dates does, because a tire is
never in two places on the same day.

Pure. Takes ORM objects but touches no session, so the unit tests build
periods in memory, and every writer calls it over the tire's RESULTING period
list after a flush and before the commit.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.models.tire import TireMountPeriod, TireReading
from app.services.usage_axis import DistanceFormatter as DistanceFormatter
from app.services.usage_axis import distance_formatter as distance_formatter
from app.services.usage_axis import format_km as format_km
from app.utils.odometer_tolerance import odometer_above, odometer_below

REVERSED_DATES = "reversed_dates"
REVERSED_ODOMETER = "reversed_odometer"
OVERLAPPING_DATES = "overlapping_dates"
OVERLAPPING_ODOMETER = "overlapping_odometer"
CONTRADICTS_READING = "contradicts_reading"


@dataclass(frozen=True)
class PeriodFault:
    """One contradiction, on the period that introduces it.

    `counterpart_id` is the period it contradicts, for the pair rules. Both
    are participants: a write that touches EITHER side of a persisting
    contradiction is refused by default, unless that write strictly shrinks
    the full set of fault keys elsewhere, in which case this same key can
    pass through worse than before (see `new_or_touched_faults`).
    """

    period_id: int
    code: str
    message: str
    counterpart_id: int | None = None

    @property
    def key(self) -> tuple[int, str, int | None]:
        return (self.period_id, self.code, self.counterpart_id)

    @property
    def participants(self) -> frozenset[int]:
        return frozenset(i for i in (self.period_id, self.counterpart_id) if i is not None)


def _label(period: TireMountPeriod, *, capital: bool = False) -> str:
    """A period as the history drawer shows it: by corner and mount date.

    Never by id. The drawer renders no period ids, so a message saying
    "period 12" named a row the user had no way to find. Two periods of one
    tire at one corner with the same mount date, or with both mount dates
    unknown, read alike; the drawer lists them in mount order, and the dates
    and odometers in the rest of the sentence usually tell them apart.
    """
    article = "The" if capital else "the"
    corner = f"{period.position} period" if period.position else "period"
    if period.mounted_on is None:
        return f"{article} {corner} with an unknown mount date"
    return f"{article} {corner} mounted {period.mounted_on.isoformat()}"


def odometer_contradictions(
    periods: Sequence[TireMountPeriod], readings: Sequence[TireReading]
) -> list[tuple[TireMountPeriod, TireReading]]:
    """C5: every (period, reading) pair whose odometer bounds contradict the reading's date.

    The invariant is that a vehicle's odometer does not run backwards in
    time. Relating a reading to a period's mount and dismount, that
    invariant yields four implications, all enforced here:

    1. A reading dated AFTER `dismounted_on` cannot read BELOW
       `dismounted_odometer_km` (the odometer would have to have gone down
       since the dismount).
    2. A reading dated BEFORE `mounted_on` cannot read ABOVE
       `mounted_odometer_km` (the odometer would have to go down between the
       reading and the mount).
    3. A reading dated AFTER `mounted_on` cannot read BELOW
       `mounted_odometer_km` (the odometer would have to have gone down
       since the mount).
    4. A reading dated BEFORE `dismounted_on` cannot read ABOVE
       `dismounted_odometer_km` (the odometer would have to go down between
       the reading and the dismount).

    A violation of any of the four means the dates and the odometers
    describe two different histories, which is what an odometer reset looks
    like.

    Every comparison is STRICT on the date, never `>=`/`<=`. These dates are
    day-granular, so two events recorded on the same calendar day cannot be
    ordered: a tire legitimately measured on the morning of its mount day can
    read slightly below the mount odometer, because the vehicle was driven
    between the measurement and the mount later that day. On the boundary
    day the true order is unknowable, so it must not be judged. The same
    applies symmetrically to a reading taken on the day of a dismount.

    Stated as monotonicity, NOT as range membership. An earlier revision
    asked whether a reading's odometer fell inside a period's odometer range
    while its date fell outside that period's dates, which assumes an
    odometer value identifies a date. It does not: a parked vehicle holds one
    odometer reading across many days, so a tire dismounted at 12,000 and
    measured in storage two days later at 12,000 was rejected as corrupt, and
    two periods sharing an endpoint odometer rejected each other's boundary
    readings.

    Only bounds that are actually known take part. A null is unknown, not
    wrong, which is what keeps the migrated assumed period out of this.

    The odometer comparisons use the same-reading band
    (`app.utils.odometer_tolerance`): a reading within a few parts per million
    of a bound is that bound, as a figure saved before v3.4.0 is the same
    figure retyped today. Only a reading beyond the band runs backwards.

    Pairs, not period ids, and here rather than in `tire_service`: the
    projection needs only which periods to withhold a figure over (its
    `_odometer_goes_backwards` reduces these pairs to ids), while a write-time
    refusal has to name the READING, because a mistyped reading is as likely
    as a mistyped period and deleting it is the repair. One rule, two callers.
    Each pair appears once however many implications it violates, in the
    order of `periods`, then of `readings`.
    """
    pairs: list[tuple[TireMountPeriod, TireReading]] = []
    for period in periods:
        for reading in readings:
            odometer = reading.odometer_km
            if odometer is None:
                continue
            day = reading.recorded_at
            backwards = False
            dismounted_on, dismounted_at = period.dismounted_on, period.dismounted_odometer_km
            if dismounted_on is not None and dismounted_at is not None:
                if day > dismounted_on and odometer_below(odometer, dismounted_at):
                    backwards = True
                if day < dismounted_on and odometer_above(odometer, dismounted_at):
                    backwards = True
            mounted_on, mounted_at = period.mounted_on, period.mounted_odometer_km
            if mounted_on is not None and mounted_at is not None:
                if day < mounted_on and odometer_above(odometer, mounted_at):
                    backwards = True
                if day > mounted_on and odometer_below(odometer, mounted_at):
                    backwards = True
            if backwards:
                pairs.append((period, reading))
    return pairs


def validate_period_history(
    periods: Sequence[TireMountPeriod],
    readings: Sequence[TireReading],
    *,
    format_distance: DistanceFormatter = format_km,
) -> list[PeriodFault]:
    """Every contradiction in this tire's history, or an empty list.

    Every comparison is STRICT, so a same-day dismount and remount, and a
    remount at exactly the last dismount odometer, pass: that is what a
    rotation looks like. Odometers are compared outside the same-reading band
    (`app.utils.odometer_tolerance`), so a remount at a figure saved before
    v3.4.0, a few parts per million below the same dismount odometer typed
    today, also passes. An unknown bound is a gap, never a fault; the
    migrated assumed period has two of them.

    Rules 1, 2 and 5 look at every period. Rules 3 and 4 are orderings, and
    each runs ONLY over the periods whose ordering key is known: the mount
    date for 3 and 4a, a fully known odometer span for 4b. A period with an
    unknown key is neither judged nor used to judge others. Rules 3 and 4a
    name every earlier period a later one contradicts, so one period can carry
    several faults of one code, one per counterpart. Sorting unknown dates as "earliest", the
    way the response sorts for display, is wrong here: clearing a later open
    period's mount date would sort it first, and every earlier closed period
    would then "start while it is still open".

    Faults name the LATER period of a pair, the one that intrudes on history
    already recorded.

    `format_distance` renders every odometer that appears in a fault message,
    in `format_km`'s wording by default. It shapes message text only: which
    faults are raised, their codes and their keys never depend on it.
    """
    faults: list[PeriodFault] = []
    seen: set[tuple[int, str, int | None]] = set()

    def add(
        period: TireMountPeriod,
        code: str,
        message: str,
        counterpart: TireMountPeriod | None = None,
    ) -> None:
        fault = PeriodFault(period.id, code, message, counterpart.id if counterpart else None)
        if fault.key not in seen:
            seen.add(fault.key)
            faults.append(fault)

    # 1 and 2: a period against itself.
    for p in periods:
        if (
            p.mounted_on is not None
            and p.dismounted_on is not None
            and p.dismounted_on < p.mounted_on
        ):
            add(
                p,
                REVERSED_DATES,
                f"{_label(p, capital=True)} is dismounted on {p.dismounted_on}, before it was "
                "mounted.",
            )
        if (
            p.mounted_odometer_km is not None
            and p.dismounted_odometer_km is not None
            and odometer_below(p.dismounted_odometer_km, p.mounted_odometer_km)
        ):
            add(
                p,
                REVERSED_ODOMETER,
                f"{_label(p, capital=True)} is dismounted at "
                f"{format_distance(p.dismounted_odometer_km)}, below its mount odometer of "
                f"{format_distance(p.mounted_odometer_km)}.",
            )

    # 3: dates, over periods with a known mount date, in date order. Each
    # period is judged against EVERY earlier one, not a running maximum. A
    # running maximum names only the period holding it, so an earlier period
    # that also contradicts the later one is no participant of any fault, and
    # the incremental policy cannot see a write that made it contradict. Rule 3
    # could not actually hide one that way (every dated period is both judged
    # and a possible counterpart); it is written like 4a so the two stay one
    # shape.
    dated = sorted(
        (p for p in periods if p.mounted_on is not None), key=lambda p: (p.mounted_on, p.id or 0)
    )
    for index, q in enumerate(dated):
        # Narrowed again for pyright, which cannot see the filter that built
        # `dated` through the generator.
        mounted_on = q.mounted_on
        assert mounted_on is not None
        for earlier in dated[:index]:
            if earlier.dismounted_on is None:
                add(
                    q,
                    OVERLAPPING_DATES,
                    f"{_label(q, capital=True)} starts while {_label(earlier)} is still open.",
                    counterpart=earlier,
                )
            elif mounted_on < earlier.dismounted_on:
                add(
                    q,
                    OVERLAPPING_DATES,
                    f"{_label(q, capital=True)} starts before {_label(earlier)} was dismounted "
                    f"on {earlier.dismounted_on}.",
                    counterpart=earlier,
                )
            # 4a rides along the same chronological order: the odometer cannot
            # go down between a known earlier dismount and a known later mount.
            # This is the rule a running maximum really did hide behind: a
            # period with a dismount odometer and no mount odometer can be a
            # counterpart but is never judged, so nothing else names it.
            if (
                q.mounted_odometer_km is not None
                and earlier.dismounted_odometer_km is not None
                and odometer_below(q.mounted_odometer_km, earlier.dismounted_odometer_km)
            ):
                add(
                    q,
                    OVERLAPPING_ODOMETER,
                    f"{_label(q, capital=True)} is mounted at "
                    f"{format_distance(q.mounted_odometer_km)}, below the "
                    f"{format_distance(earlier.dismounted_odometer_km)} at which "
                    f"{_label(earlier)} was dismounted.",
                    counterpart=earlier,
                )

    # 4b: order-free. Two fully bounded spans that intersect by more than the
    # same-reading band are a contradiction whatever their dates say: a tire
    # cannot be in two places at once. Sorted by mount odometer; the
    # later-by-odometer span is the intruder. Where 4a already named the same
    # pair, `add` deduplicates.
    #
    # A running maximum works HERE, unlike in 3 and 4a, because every span is
    # both judged and a possible counterpart. An earlier span P that a later
    # span intersects, without holding the maximum, is itself a participant: if
    # P is not an intruder, the maximum after P is P's own dismount, so the
    # next span in order (whose mount is below it) is reported against P.
    #
    # Only one counterpart is named at a time, though, so which one can lag
    # behind the full picture: a span may genuinely intersect more than one
    # earlier span, and only the one currently holding the maximum is named.
    # That never drops a period's own `(period, code)` flag, so nothing goes
    # unreported; a contradiction hidden behind the one currently named
    # becomes its own key, for `new_or_touched_faults` to see, once the fault
    # naming it is repaired.
    spans = sorted(
        (
            p
            for p in periods
            if p.mounted_odometer_km is not None and p.dismounted_odometer_km is not None
        ),
        key=lambda p: (p.mounted_odometer_km, p.id or 0),
    )
    covered: tuple[Decimal, TireMountPeriod] | None = None
    for q in spans:
        # Narrowed for pyright, which cannot see the filter that built `spans`.
        start = q.mounted_odometer_km
        assert start is not None
        if covered is not None and odometer_below(start, covered[0]):
            add(
                q,
                OVERLAPPING_ODOMETER,
                f"{_label(q, capital=True)} claims distance {_label(covered[1])} already "
                f"covers: it starts at {format_distance(start)}, before that "
                f"period ended at {format_distance(covered[0])}.",
                counterpart=covered[1],
            )
        # The TRUE maximum, by a plain comparison and not outside the band. A
        # maximum that moved only when a dismount cleared the band could lag
        # a span ending within the band above it, and a later span starting
        # beyond the band below that span's end, a genuine overlap, would be
        # judged against the lower figure and pass.
        if covered is None or q.dismounted_odometer_km > covered[0]:
            # `spans` is filtered to periods with a known dismount odometer;
            # this asserts that invariant for pyright, which cannot see
            # through the generator filter that built `spans`.
            end = q.dismounted_odometer_km
            assert end is not None
            covered = (end, q)

    # 5: the projection's own monotonicity rule, the same function it calls.
    # One fault per period, naming the EARLIEST reading it contradicts, so the
    # sentence is stable whatever order the readings were loaded in. The
    # message says what to do, because until readings could be deleted a
    # mistyped one refused every honest dismount, retire, rotation, set fit
    # and remount of its tire with no way out.
    in_order = sorted(readings, key=lambda r: (r.recorded_at, r.id or 0))
    for p, reading in odometer_contradictions(sorted(periods, key=lambda p: p.id or 0), in_order):
        # `odometer_contradictions` pairs only readings with an odometer.
        odometer = reading.odometer_km
        assert odometer is not None
        add(
            p,
            CONTRADICTS_READING,
            f"{_label(p, capital=True)} contradicts the reading dated {reading.recorded_at} at "
            f"{format_distance(odometer)}: the vehicle's odometer would have to run backwards. "
            "If that reading is wrong, delete it from the tire's history.",
        )
    return faults


FaultMap = dict[tuple[int, str, int | None], PeriodFault]


def fault_map(
    periods: Sequence[TireMountPeriod],
    readings: Sequence[TireReading],
    *,
    format_distance: DistanceFormatter = format_km,
) -> FaultMap:
    """`validate_period_history` keyed by (period, code, counterpart), for a before/after
    comparison. `format_distance` shapes message text only; keys and codes never depend on it.
    """
    return {
        f.key: f
        for f in validate_period_history(periods, readings, format_distance=format_distance)
    }


def new_or_touched_faults(
    before: FaultMap, after: FaultMap, touched: set[int]
) -> list[PeriodFault]:
    """The faults a write must refuse: any it introduced, and any persisting one
    that a period it touched participates in, unless the write is a strict
    improvement.

    Writers before v3.4.0 committed without validation, so a tire can carry
    two independently contradictory legacy periods. Refusing every fault
    would make that history unrepairable (fixing either period leaves the
    other) and the tire undismountable. A write is judged on what it changed:
    a fault that was already there, on periods it did not touch, survives and
    stays flagged on the wire, to be repaired in its own turn. Judged on
    PARTICIPANTS, not on the intruder alone: touching either side of a
    persisting overlap counts against the write by default; whether the write
    still goes through depends on the full key set, below. An edit that only
    makes the overlap worse, resolving nothing else, is refused.

    The faults about a touched period come first, keeping their order among
    themselves: a writer raises the first one, and the sentence a user reads
    should be about the change they just made.

    "Introduced" means the period now carries a CODE it did not carry before:
    a fault is new when its `(period_id, code)` was not faulted in `before`.
    The counterpart is deliberately left out of that test. Rules 3 and 4a name
    every earlier period a later one contradicts, so their faults never change
    counterpart. Rule 4b still names a running maximum, the span holding the
    highest dismount odometer so far, so repairing that span hands the maximum
    to the next one and re-labels an untouched 4b fault against a different
    counterpart. Judged by the full key, that relabelled fault would read as
    new and refuse the honest repair. Nothing is lost by leaving the
    counterpart out: whether two untouched periods contradict depends only on
    their own bounds, so a write can change which counterpart an untouched
    period's fault names but cannot give that period a code it did not
    already carry, and a fault whose new counterpart IS a touched period adds
    a key nothing in `before` had, so it can never be part of a strict shrink
    (below) and is still refused through its participants. `FaultMap` keeps the full triple so each counterpart is
    still a participant.

    A write that leaves a touched period in a persisting contradiction is
    nonetheless accepted when the full fault-key set strictly shrinks: at
    least one fault key resolved, no fault key added. That is what makes two
    legacy typos that contradict each other repairable one period at a time,
    in either order. An overlap made worse without resolving anything leaves
    the key set unchanged, so it is still refused. A write that resolves one
    contradiction while enlarging another's magnitude is accepted, and the
    enlarged one stays flagged on the tire's history until it is repaired in
    its own turn. Rule 4b's running maximum and rule 5's one-fault-per-period
    already let several genuine contradictions share a single key, so a
    strict shrink can also land a brand new contradiction under a key some
    other period already carries: that period's own flag never goes missing,
    so the new contradiction gets its own key, and this rule's attention,
    once the fault currently sharing that key is repaired.
    """
    if set(after) < set(before):
        return []
    pre_existing = {(f.period_id, f.code) for f in before.values()}
    refused = [
        f
        for f in after.values()
        if (f.period_id, f.code) not in pre_existing or (f.participants & touched)
    ]
    # Stable, so the validator's order holds within each group.
    return sorted(refused, key=lambda f: not (f.participants & touched))

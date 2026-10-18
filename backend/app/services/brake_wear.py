"""Brake wear: which measurements count, the estimate, and the corner's condition (#202).

Pure, no session. `brake_service` loads the rows and hands them here, so the
card, the reminder and the tests all read one set of rules.

The rules, in short:

- A corner's pads (or shoes) start over at its latest brake job that replaced
  them, for the brakes the axle has now: a job of the other kind says nothing
  about these. Only measurements after that job count: dated after it, or written by
  it (the new-pads figure, `brake_job_id`). A same-day measurement the job
  didn't write is taken as the OLD pads, measured before they came off.
- Each pad (inner and outer, or the shoe) is estimated on its own checks. A
  one-pad check carries the other pad's figure forward for the card, the
  minimum and the band, but says nothing about how that pad has worn since.
- A pad's rate comes from its oldest check and its last, the longest baseline
  there is. Pad wear between two checks is often less than a gauge can read,
  so the newest two alone would mostly measure noise. Both ends need the
  figure the estimate runs on (odometer, or hours on an hours-only vehicle).
- What a pad has left is worked out at its last check, less the distance (or
  hours) run up to the newest check with a reading, and dated from that check.
  When the newest check itself has no reading the use since is unknown, so
  the pad gets a date and no distance.
- The corner reads whichever comes first: the least distance left and the
  earliest date, each over its pads, as long as its thinnest pad has an
  estimate. Each pad runs at the pace of its own checks, so the two can come
  from different pads. When the thinnest has none, the corner says why, and
  the other pad's date still counts toward the chip: the corner can't outlast it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Literal

from app.models.brake import BrakeAxle, BrakeJob, BrakeMeasurement
from app.services.usage_axis import UsageAxis

Axle = Literal["front", "rear"]
BrakeType = Literal["disc", "drum"]
BrakePosition = Literal["FL", "FR", "RL", "RR"]

POSITIONS: tuple[BrakePosition, ...] = ("FL", "FR", "RL", "RR")
AXLES: tuple[Axle, ...] = ("front", "rear")
AXLE_OF: dict[str, Axle] = {"FL": "front", "FR": "front", "RL": "rear", "RR": "rear"}

#: A corner is due soon this long before its projected wear date.
DUE_SOON_DAYS = 90
#: ...or once its thinnest pad is in the last quarter of the usable range.
DUE_SOON_SHARE = Decimal("0.25")


@dataclass(frozen=True)
class AxleLimits:
    """The defaults an axle gets until someone saves Axle setup."""

    min_thickness_mm: Decimal
    new_thickness_mm: Decimal


DEFAULT_LIMITS: dict[BrakeType, AxleLimits] = {
    "disc": AxleLimits(Decimal("3.00"), Decimal("10.00")),
    "drum": AxleLimits(Decimal("1.50"), Decimal("5.00")),
}


@dataclass(frozen=True)
class AxleSetup:
    """One axle's setup: the saved row, or the disc defaults when there is none."""

    axle: Axle
    brake_type: BrakeType
    min_thickness_mm: Decimal
    new_thickness_mm: Decimal
    rotor_min_mm: Decimal | None
    drum_max_mm: Decimal | None
    configured: bool

    @property
    def due_soon_mm(self) -> Decimal:
        """The thickness at or below which a corner is due soon.

        Rounded to the hundredth every stored figure has, so the band the card
        shows is the band the corner is judged on (a drum's 2.375 reads 2.38).
        """
        usable = self.new_thickness_mm - self.min_thickness_mm
        band = self.min_thickness_mm + DUE_SOON_SHARE * max(usable, Decimal("0"))
        return band.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def axle_setup(axle: Axle, row: BrakeAxle | None) -> AxleSetup:
    """The axle's setup from its row, or the disc defaults when it has none."""
    if row is None:
        limits = DEFAULT_LIMITS["disc"]
        return AxleSetup(
            axle=axle,
            brake_type="disc",
            min_thickness_mm=limits.min_thickness_mm,
            new_thickness_mm=limits.new_thickness_mm,
            rotor_min_mm=None,
            drum_max_mm=None,
            configured=False,
        )
    brake_type: BrakeType = "drum" if row.brake_type == "drum" else "disc"
    return AxleSetup(
        axle=axle,
        brake_type=brake_type,
        min_thickness_mm=row.min_thickness_mm,
        new_thickness_mm=row.new_thickness_mm,
        rotor_min_mm=row.rotor_min_mm,
        drum_max_mm=row.drum_max_mm,
        configured=True,
    )


class BrakeWearStatus(StrEnum):
    """Why a corner has the estimate it has, or none."""

    PROJECTED = "projected"
    AT_OR_BELOW_MINIMUM = "at_or_below_minimum"
    #: Nothing measured for this corner's brake type.
    NO_MEASUREMENTS = "no_measurements"
    #: A brake job replaced the pads and nothing has been measured since.
    REPLACED_NOT_MEASURED = "replaced_not_measured"
    #: One measurement since the pads went on; an estimate needs two.
    INSUFFICIENT_MEASUREMENTS = "insufficient_measurements"
    #: The thinnest pad's last check, or all but one of its checks, lack the
    #: odometer (or hours). `reading_needed_on` says which, when it is one.
    NO_USAGE_FIGURES = "no_usage_figures"
    #: The thinnest pad's first and last checks sit at the same odometer (or hours).
    NO_USAGE_BETWEEN = "no_usage_between"
    #: The thinnest pad reads as thick as, or thicker than, it did, or was
    #: measured only once.
    NOT_DECREASING = "not_decreasing"


class BrakeCondition(StrEnum):
    """What the corner's chip says, and what the axle reminder reads."""

    OK = "ok"
    DUE_SOON = "due_soon"
    REPLACE_NOW = "replace_now"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class BrakeWear:
    """A corner's wear estimate, with the reason when there is none.

    `usage_remaining` is what is left as of the newest measurement, never below
    zero: distance in km, or hours on the hours axis. Null on a projection
    means the newest measurement has no reading, so the estimate is a date
    alone. Null `wear_date` on a projection means no pad has a date: its checks
    share a day, or it lands past the calendar. Read `status` for whether it projected.
    """

    status: BrakeWearStatus
    #: The newest measurement that measured the pads, in the current segment.
    latest: BrakeMeasurement | None = None
    #: The newest inner and outer pad (disc) or shoe (drum) known in the segment,
    #: each from whichever measurement last took it.
    inner_pad_mm: Decimal | None = None
    outer_pad_mm: Decimal | None = None
    shoe_mm: Decimal | None = None
    #: When each of those was measured: a one-pad check carries the other
    #: pad's figure from an older measurement.
    inner_measured_on: dt.date | None = None
    outer_measured_on: dt.date | None = None
    #: The thinnest of those: what the minimum and the band are judged on,
    #: and the day it was measured. On a tie, the older figure: it has worn since.
    thinnest_mm: Decimal | None = None
    thinnest_measured_on: dt.date | None = None
    usage_remaining: Decimal | None = None
    wear_date: dt.date | None = None
    #: On `no_usage_figures`, the measurement that needs the reading: the
    #: thinnest pad's last check. None when it has one and an earlier is missing.
    reading_needed_on: dt.date | None = None
    #: The earliest day a pad with an estimate reaches the minimum: what the
    #: chip and the reminder run on. `wear_date` on a projection; still set
    #: when the thinnest pad has no estimate of its own, since the corner
    #: can't outlast its other pad.
    worn_by: dt.date | None = None


def _order(m: BrakeMeasurement) -> tuple[dt.date, int]:
    return (m.recorded_at, m.id or 0)


def pad_thickness(m: BrakeMeasurement, brake_type: str) -> Decimal | None:
    """The thinner pad this one measurement took on a disc corner, or its shoe on a drum one."""
    if brake_type == "drum":
        return m.shoe_mm
    known = [v for v in (m.inner_pad_mm, m.outer_pad_mm) if v is not None]
    return min(known) if known else None


def surface_figure(m: BrakeMeasurement, brake_type: str) -> Decimal | None:
    """The rotor thickness on a disc corner, or the drum diameter on a drum one."""
    return m.drum_mm if brake_type == "drum" else m.rotor_mm


def latest_job(jobs: Iterable[BrakeJob], wanted: Callable[[BrakeJob], bool]) -> BrakeJob | None:
    """The newest job, by (date, id), that `wanted` accepts."""
    return max(
        (j for j in jobs if wanted(j)), key=lambda j: (j.performed_on, j.id or 0), default=None
    )


def after_job(m: BrakeMeasurement, job: BrakeJob | None) -> bool:
    """Whether a measurement belongs to what the job put on.

    Written by the job, or dated after it. A same-day measurement the job did
    not write is the old part, measured on the way off.
    """
    if job is None:
        return True
    return (m.brake_job_id is not None and m.brake_job_id == job.id) or (
        m.recorded_at > job.performed_on
    )


def _friction_job(jobs: Iterable[BrakeJob], setup: AxleSetup) -> BrakeJob | None:
    """The corner's latest pad (or shoe) job, for the brakes the axle has now.

    One logged before a type change replaced the other kind, so it neither
    starts these pads over nor counts as them replaced.
    """
    return latest_job(jobs, lambda j: j.friction_replaced and j.brake_type == setup.brake_type)


def pad_checks(
    measurements: Iterable[BrakeMeasurement], jobs: Iterable[BrakeJob], setup: AxleSetup
) -> list[BrakeMeasurement]:
    """The corner's measurements the estimate runs on, oldest first.

    After its latest pad (or shoe) job, with a pad figure of the axle's type.
    A rotor-only check, or one from before that job, says nothing about these pads.
    """
    job = _friction_job(jobs, setup)
    return sorted(
        (
            m
            for m in measurements
            if after_job(m, job) and pad_thickness(m, setup.brake_type) is not None
        ),
        key=_order,
    )


def estimate_reads(
    row: BrakeMeasurement | BrakeJob,
    measurements: Sequence[BrakeMeasurement],
    jobs: Sequence[BrakeJob],
    setup: AxleSetup,
    axis: UsageAxis,
) -> frozenset[str]:
    """The fields of one of the corner's rows that its pad estimate reads, if any.

    A pad check: its pad figures, its date and the reading the rate runs on.
    The pad job: that it replaced the pads, and its date. Any job: the date
    and reading it carries over to a new-pads figure it wrote, while that
    figure is a pad check (a disc job's figure given a shoe after the axle
    went drum still is). A rotor-only check, history from before the pad job
    (an older pad job too, or one dated back behind another) and the other
    brake type's records it doesn't read at all.
    """
    reading = "engine_hours" if axis.is_hours else "odometer_km"
    checks = pad_checks(measurements, jobs, setup)
    if isinstance(row, BrakeMeasurement):
        if all(m.id != row.id for m in checks):
            return frozenset()
        return frozenset({*_PAD_FIELDS[setup.brake_type].values(), "recorded_at", reading})
    reads: set[str] = set()
    job = _friction_job(jobs, setup)
    if job is not None and job.id == row.id:
        reads |= {"friction_replaced", "performed_on"}
    if any(m.brake_job_id == row.id for m in checks):
        # What `BrakeService.update_job` moves on the figure it wrote.
        reads |= {"performed_on", reading}
    return frozenset(reads)


def _usage(m: BrakeMeasurement, axis: UsageAxis) -> Decimal | None:
    return m.engine_hours if axis.is_hours else m.odometer_km


#: One pad's checks in the segment, oldest first: the measurement and its figure.
_Checks = list[tuple[BrakeMeasurement, Decimal]]

_PAD_FIELDS: dict[str, dict[str, str]] = {
    "disc": {"inner": "inner_pad_mm", "outer": "outer_pad_mm"},
    "drum": {"shoe": "shoe_mm"},
}


def _pads(measured: Sequence[BrakeMeasurement], brake_type: str) -> dict[str, _Checks]:
    """Each pad (or the shoe) with the checks that read it, oldest first.

    A disc check often reads one pad only: the outer one shows through the
    wheel, the inner one needs the wheel off. Keeping each pad's own checks
    lets a quick outer check stand beside the inner pad's last figure, so it
    can't hide an inner pad already near the minimum. A pad never read is left out.
    """
    pads: dict[str, _Checks] = {}
    for name, field in _PAD_FIELDS[brake_type].items():
        checks = [(m, value) for m in measured if (value := getattr(m, field)) is not None]
        if checks:
            pads[name] = checks
    return pads


@dataclass(frozen=True)
class _Estimate:
    """One pad's estimate, or why it has none."""

    status: BrakeWearStatus
    usage_remaining: Decimal | None = None
    wear_date: dt.date | None = None
    reading_needed_on: dt.date | None = None


def _project_pad(
    checks: _Checks, measured: Sequence[BrakeMeasurement], minimum: Decimal, axis: UsageAxis
) -> _Estimate:
    """How long one pad has left, from its own checks. The pad is above the minimum.

    `measured` is every pad check on the corner, oldest first: the use since
    this pad was read comes from whichever has the newest reading.
    """
    if len(checks) < 2:
        # Measured once: no wear seen on it yet.
        return _Estimate(BrakeWearStatus.NOT_DECREASING)
    last, value = checks[-1]
    last_usage = _usage(last, axis)
    if last_usage is None:
        return _Estimate(BrakeWearStatus.NO_USAGE_FIGURES, reading_needed_on=last.recorded_at)
    figured = [(m, v) for m, v in checks if _usage(m, axis) is not None]
    if len(figured) < 2:
        return _Estimate(BrakeWearStatus.NO_USAGE_FIGURES)

    first, first_value = figured[0]
    first_usage = _usage(first, axis)
    assert first_usage is not None  # filtered above
    usage_delta = last_usage - first_usage
    if usage_delta <= 0:
        return _Estimate(BrakeWearStatus.NO_USAGE_BETWEEN)
    worn = first_value - value
    if worn <= 0:
        return _Estimate(BrakeWearStatus.NOT_DECREASING)
    left_then = (value - minimum) * usage_delta / worn
    days = (last.recorded_at - first.recorded_at).days

    def date_after(start: dt.date, usage: Decimal) -> dt.date | None:
        """The day `usage` runs out after `start`, at this pad's own pace."""
        if days <= 0:
            return None
        days_left = int(usage * days / usage_delta)
        # A crawl of a rate lands past the calendar, and timedelta would raise.
        if days_left > (dt.date.max - start).days:
            return None
        return start + timedelta(days=days_left)

    # The newest check with a reading: this pad's own last one at worst.
    anchor = next(m for m in reversed(measured) if _usage(m, axis) is not None)
    anchor_usage = _usage(anchor, axis)
    assert anchor_usage is not None  # picked for it
    # Never more than was left when measured: an odometer entered lower later on
    # would otherwise hand distance back.
    used_since = max(anchor_usage - last_usage, Decimal("0"))
    remaining = max(left_then - used_since, Decimal("0"))
    # Worn down by the anchor: that's its date, with or without a pace to
    # count days at (a same-day baseline has none).
    wear_date = anchor.recorded_at if remaining == 0 else date_after(anchor.recorded_at, remaining)
    if anchor is not measured[-1]:
        # The newest check has no reading, so the use since the anchor is
        # unknown: a date alone, as of the anchor.
        return _Estimate(BrakeWearStatus.PROJECTED, None, wear_date)
    return _Estimate(BrakeWearStatus.PROJECTED, remaining, wear_date)


def project_brake_wear(
    measurements: Sequence[BrakeMeasurement],
    jobs: Sequence[BrakeJob],
    setup: AxleSetup,
    axis: UsageAxis,
) -> BrakeWear:
    """Estimate how long one corner's pads (or shoes) have left.

    Args:
        measurements: The corner's measurements, any order.
        jobs: The corner's brake jobs, any order.
        setup: The corner's axle setup: brake type and minimum.
        axis: Which figure the rate runs on.
    """
    measured = pad_checks(measurements, jobs, setup)
    if not measured:
        status = (
            BrakeWearStatus.REPLACED_NOT_MEASURED
            if _friction_job(jobs, setup) is not None
            else BrakeWearStatus.NO_MEASUREMENTS
        )
        return BrakeWear(status=status)

    pads = _pads(measured, setup.brake_type)
    newest = measured[-1]
    # The thinnest figure, and on a tie the older one: it has worn since.
    thinnest_pad = min(pads, key=lambda name: (pads[name][-1][1], _order(pads[name][-1][0])))
    seen, thinnest = pads[thinnest_pad][-1]

    def figure(name: str) -> Decimal | None:
        return pads[name][-1][1] if name in pads else None

    def measured_on(name: str) -> dt.date | None:
        return pads[name][-1][0].recorded_at if name in pads else None

    def result(
        status: BrakeWearStatus,
        *,
        usage_remaining: Decimal | None = None,
        wear_date: dt.date | None = None,
        reading_needed_on: dt.date | None = None,
        worn_by: dt.date | None = None,
    ) -> BrakeWear:
        return BrakeWear(
            status=status,
            latest=newest,
            inner_pad_mm=figure("inner"),
            outer_pad_mm=figure("outer"),
            shoe_mm=figure("shoe"),
            inner_measured_on=measured_on("inner"),
            outer_measured_on=measured_on("outer"),
            thinnest_mm=thinnest,
            thinnest_measured_on=seen.recorded_at,
            usage_remaining=usage_remaining,
            wear_date=wear_date,
            reading_needed_on=reading_needed_on,
            worn_by=worn_by,
        )

    minimum = setup.min_thickness_mm
    if thinnest <= minimum:
        # A safety statement that needs no rate: dated by the measurement that
        # showed it, which a carried pad makes older than the newest one.
        return result(
            BrakeWearStatus.AT_OR_BELOW_MINIMUM,
            usage_remaining=axis.zero,
            wear_date=seen.recorded_at,
        )
    if len(measured) < 2:
        return result(BrakeWearStatus.INSUFFICIENT_MEASUREMENTS)

    estimates = {
        name: _project_pad(checks, measured, minimum, axis) for name, checks in pads.items()
    }
    projected = [e for e in estimates.values() if e.status is BrakeWearStatus.PROJECTED]
    # Whichever comes first, distance and date each on their own: every pad
    # runs at the pace of its own checks, so the one with the least distance
    # left can still have the later date.
    worn_by = min((e.wear_date for e in projected if e.wear_date is not None), default=None)
    own = estimates[thinnest_pad]
    if own.status is not BrakeWearStatus.PROJECTED:
        # The thinnest pad has no estimate, and a thicker pad's would overstate
        # the corner: say why instead, and let the other pad's date count toward the chip.
        return result(own.status, reading_needed_on=own.reading_needed_on, worn_by=worn_by)
    # All or none have one: the newest check's reading decides.
    remaining = min(
        (e.usage_remaining for e in projected if e.usage_remaining is not None), default=None
    )
    return result(
        BrakeWearStatus.PROJECTED,
        usage_remaining=remaining.quantize(Decimal("0.1")) if remaining is not None else None,
        wear_date=worn_by,
        worn_by=worn_by,
    )


def brake_condition(wear: BrakeWear, setup: AxleSetup, today: dt.date) -> BrakeCondition:
    """The corner's chip, from its estimate and the axle's limits."""
    if wear.status is BrakeWearStatus.AT_OR_BELOW_MINIMUM:
        return BrakeCondition.REPLACE_NOW
    if wear.status is BrakeWearStatus.NO_MEASUREMENTS:
        return BrakeCondition.UNKNOWN
    if wear.status is BrakeWearStatus.REPLACED_NOT_MEASURED:
        return BrakeCondition.OK
    if _in_band(wear, setup):
        return BrakeCondition.DUE_SOON
    if wear.worn_by is not None and wear.worn_by <= today + timedelta(days=DUE_SOON_DAYS):
        return BrakeCondition.DUE_SOON
    return BrakeCondition.OK


def _in_band(wear: BrakeWear, setup: AxleSetup) -> bool:
    return wear.thinnest_mm is not None and wear.thinnest_mm <= setup.due_soon_mm


def reminder_due(wear: BrakeWear, condition: BrakeCondition, setup: AxleSetup) -> dt.date | None:
    """When a LOW corner's reminder falls due, or None for a corner that isn't LOW.

    Dated from the measurements, never from today, so a later write that
    changes nothing about the corner doesn't move the date. Replace now is due
    the day the thinnest figure was measured. A pad in the band is due at its
    wear date, or `DUE_SOON_DAYS` after that day, whichever comes first: it
    wants a look within that long whatever the rate says. Due soon by the wear
    date alone is due on that date.
    """
    seen = wear.thinnest_measured_on
    if seen is None:
        return None
    if condition is BrakeCondition.REPLACE_NOW:
        return seen
    if condition is not BrakeCondition.DUE_SOON:
        return None
    if not _in_band(wear, setup):
        # The recheck below is for a pad in the band. Here it would date a
        # reminder that time alone raised before the day it was raised.
        return wear.worn_by
    # From the day the thinnest figure was seen, not the newest check: a
    # quick outer-pad look doesn't restart the clock on a low inner pad.
    recheck = seen + timedelta(days=DUE_SOON_DAYS)
    return min(wear.worn_by, recheck) if wear.worn_by is not None else recheck


@dataclass(frozen=True)
class SurfaceReading:
    """The newest rotor thickness or drum diameter since the rotor or drum last changed."""

    value_mm: Decimal
    measured_on: dt.date
    past_limit: bool


def surface_reading(
    measurements: Sequence[BrakeMeasurement],
    jobs: Sequence[BrakeJob],
    setup: AxleSetup,
) -> SurfaceReading | None:
    """The corner's rotor or drum figure, flagged when it is past its limit."""
    # A rotor job says nothing about a drum, and the other way round.
    job = latest_job(jobs, lambda j: j.surface is not None and j.brake_type == setup.brake_type)
    measured = [
        m
        for m in measurements
        if after_job(m, job) and surface_figure(m, setup.brake_type) is not None
    ]
    if not measured:
        return None
    newest = max(measured, key=_order)
    value = surface_figure(newest, setup.brake_type)
    assert value is not None  # filtered above
    if setup.brake_type == "drum":
        past = setup.drum_max_mm is not None and value >= setup.drum_max_mm
    else:
        past = setup.rotor_min_mm is not None and value <= setup.rotor_min_mm
    return SurfaceReading(value_mm=value, measured_on=newest.recorded_at, past_limit=past)

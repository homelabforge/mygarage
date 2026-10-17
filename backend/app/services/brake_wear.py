"""Brake wear: which measurements count, the estimate, and the corner's condition (#202).

Pure, no session. `brake_service` loads the rows and hands them here, so the
card, the reminder and the tests all read one set of rules.

The rules, in short:

- A corner's pads (or shoes) start over at its latest brake job that replaced
  them. Only measurements after that job count: dated after it, or written by
  it (the new-pads figure, `brake_job_id`). A same-day measurement the job
  didn't write is taken as the OLD pads, measured before they came off.
- The rate comes from the oldest and the newest of those measurements, the
  longest baseline there is. Pad wear between two checks is often less than a
  gauge can read, so the newest two alone would mostly measure noise.
- The newest measurement must carry the figure the estimate runs on (odometer,
  or hours on an hours-only vehicle); remaining wear is counted from it.
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
    #: Two or more, but the newest, or all but one, lack the odometer (or hours).
    NO_USAGE_FIGURES = "no_usage_figures"
    #: The oldest and newest measurement sit at the same odometer (or hours).
    NO_USAGE_BETWEEN = "no_usage_between"
    #: The pads read as thick as, or thicker than, they did.
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

    `usage_remaining` is distance in km, or hours on the hours axis. Null
    `wear_date` on a projection means the two measurements share a date or the
    date lands past the calendar; read `status` for whether it projected.
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
    #: and the day it was measured.
    thinnest_mm: Decimal | None = None
    thinnest_measured_on: dt.date | None = None
    usage_remaining: Decimal | None = None
    wear_date: dt.date | None = None


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


def _usage(m: BrakeMeasurement, axis: UsageAxis) -> Decimal | None:
    return m.engine_hours if axis.is_hours else m.odometer_km


@dataclass(frozen=True)
class _Known:
    """What was known about the pads as of one measurement, carried forward."""

    measurement: BrakeMeasurement
    inner: Decimal | None
    outer: Decimal | None
    shoe: Decimal | None
    inner_on: dt.date | None
    outer_on: dt.date | None
    thinnest: Decimal
    thinnest_on: dt.date


def _carried_forward(measured: Sequence[BrakeMeasurement], brake_type: str) -> list[_Known]:
    """Each measurement with the pads known as of it, oldest first.

    A disc check often reads one pad only: the outer one shows through the
    wheel, the inner one needs the wheel off. A one-pad entry keeps the other
    pad's last figure, so a quick outer check can't hide an inner pad already
    near the minimum.
    """
    known: list[_Known] = []
    inner = outer = shoe = None
    inner_on = outer_on = None
    for m in measured:
        if brake_type == "drum":
            shoe = m.shoe_mm
        else:
            if m.inner_pad_mm is not None:
                inner, inner_on = m.inner_pad_mm, m.recorded_at
            if m.outer_pad_mm is not None:
                outer, outer_on = m.outer_pad_mm, m.recorded_at
        # The thinnest figure and the day it was seen; on a tie, the newer day.
        dated = [
            (value, day)
            for value, day in ((inner, inner_on), (outer, outer_on), (shoe, m.recorded_at))
            if value is not None and day is not None
        ]
        thinnest, thinnest_on = min(dated, key=lambda pair: (pair[0], -pair[1].toordinal()))
        known.append(_Known(m, inner, outer, shoe, inner_on, outer_on, thinnest, thinnest_on))
    return known


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
    job = latest_job(jobs, lambda j: j.friction_replaced)
    measured = sorted(
        (
            m
            for m in measurements
            if after_job(m, job) and pad_thickness(m, setup.brake_type) is not None
        ),
        key=_order,
    )
    if not measured:
        status = (
            BrakeWearStatus.REPLACED_NOT_MEASURED
            if job is not None
            else BrakeWearStatus.NO_MEASUREMENTS
        )
        return BrakeWear(status=status)

    known = _carried_forward(measured, setup.brake_type)
    now = known[-1]
    newest, thinnest = now.measurement, now.thinnest

    def result(
        status: BrakeWearStatus,
        usage_remaining: Decimal | None = None,
        wear_date: dt.date | None = None,
    ) -> BrakeWear:
        return BrakeWear(
            status=status,
            latest=newest,
            inner_pad_mm=now.inner,
            outer_pad_mm=now.outer,
            shoe_mm=now.shoe,
            inner_measured_on=now.inner_on,
            outer_measured_on=now.outer_on,
            thinnest_mm=thinnest,
            thinnest_measured_on=now.thinnest_on,
            usage_remaining=usage_remaining,
            wear_date=wear_date,
        )

    minimum = setup.min_thickness_mm
    if thinnest <= minimum:
        # A safety statement that needs no rate: dated by the measurement that
        # showed it, which a carried pad makes older than the newest one.
        return result(
            BrakeWearStatus.AT_OR_BELOW_MINIMUM,
            usage_remaining=axis.zero,
            wear_date=now.thinnest_on,
        )

    if len(known) < 2:
        return result(BrakeWearStatus.INSUFFICIENT_MEASUREMENTS)

    # Remaining wear is counted from the newest figure, so the newest
    # measurement must carry it: counting from an older odometer would hand
    # back distance the pads have already used.
    newest_usage = _usage(newest, axis)
    figured = [k for k in known if _usage(k.measurement, axis) is not None]
    if newest_usage is None or len(figured) < 2:
        return result(BrakeWearStatus.NO_USAGE_FIGURES)

    oldest = figured[0]
    oldest_usage = _usage(oldest.measurement, axis)
    assert oldest_usage is not None  # filtered above
    usage_delta = newest_usage - oldest_usage
    if usage_delta <= 0:
        return result(BrakeWearStatus.NO_USAGE_BETWEEN)
    worn = oldest.thinnest - thinnest
    if worn <= 0:
        return result(BrakeWearStatus.NOT_DECREASING)

    remaining = (thinnest - minimum) * usage_delta / worn
    wear_date = None
    days = (newest.recorded_at - oldest.measurement.recorded_at).days
    if days > 0:
        days_left = int(remaining * days / usage_delta)
        # A crawl of a rate lands past the calendar, and timedelta would raise.
        if days_left <= (dt.date.max - newest.recorded_at).days:
            wear_date = newest.recorded_at + timedelta(days=days_left)
    return result(
        BrakeWearStatus.PROJECTED,
        usage_remaining=remaining.quantize(Decimal("0.1")),
        wear_date=wear_date,
    )


def brake_condition(wear: BrakeWear, setup: AxleSetup, today: dt.date) -> BrakeCondition:
    """The corner's chip, from its estimate and the axle's limits."""
    if wear.status is BrakeWearStatus.AT_OR_BELOW_MINIMUM:
        return BrakeCondition.REPLACE_NOW
    if wear.status is BrakeWearStatus.NO_MEASUREMENTS:
        return BrakeCondition.UNKNOWN
    if wear.status is BrakeWearStatus.REPLACED_NOT_MEASURED:
        return BrakeCondition.OK
    if wear.thinnest_mm is not None and wear.thinnest_mm <= setup.due_soon_mm:
        return BrakeCondition.DUE_SOON
    if (
        wear.status is BrakeWearStatus.PROJECTED
        and wear.wear_date is not None
        and wear.wear_date <= today + timedelta(days=DUE_SOON_DAYS)
    ):
        return BrakeCondition.DUE_SOON
    return BrakeCondition.OK


def reminder_due(wear: BrakeWear, condition: BrakeCondition) -> dt.date | None:
    """When a LOW corner's reminder falls due, or None for a corner that isn't LOW.

    Dated from the measurements, never from today, so a later write that
    changes nothing about the corner doesn't move the date. Replace now is due
    the day the thinnest figure was measured. Due soon is due at the projected
    wear date, or `DUE_SOON_DAYS` after that day, whichever comes first: a pad
    in the last quarter wants a look within that long whatever the rate says.
    """
    seen = wear.thinnest_measured_on
    if seen is None:
        return None
    if condition is BrakeCondition.REPLACE_NOW:
        return seen
    if condition is not BrakeCondition.DUE_SOON:
        return None
    # From the day the thinnest figure was seen, not the newest check: a
    # quick outer-pad look doesn't restart the clock on a low inner pad.
    recheck = seen + timedelta(days=DUE_SOON_DAYS)
    if wear.status is BrakeWearStatus.PROJECTED and wear.wear_date is not None:
        return min(wear.wear_date, recheck)
    return recheck


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
    job = latest_job(jobs, lambda j: j.surface is not None)
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

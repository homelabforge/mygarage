"""Pure recurrence arithmetic: an anchor plus a rule's intervals gives the next
due thresholds.

Nothing here touches the database. `maintenance_service` decides WHICH anchor
applies (the most recent qualifying service, a completion, or a baseline) and
hands it in; this module only adds intervals to it, so the two questions can be
tested apart.

Each threshold is independent. A rule of 7,500 mi / 6 months from a service on
2026-06-13 at 88,896 mi is due at 96,396 mi OR on 2026-12-13, whichever the
vehicle reaches first. The date is never derived from the mileage: a driving
rate projection is a separate number (`project_usage_date`) that the UI shows
beside the thresholds and that moves as driving changes, while the thresholds
do not.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from dateutil.relativedelta import relativedelta

from app.schemas.maintenance import AnchorKind

KM_QUANTUM = Decimal("0.01")
HOURS_QUANTUM = Decimal("0.1")


class HasIntervals(Protocol):
    """What a rule (ORM row or request schema) must offer."""

    interval_km: Decimal | None
    interval_months: int | None
    interval_days: int | None
    interval_hours: Decimal | None


@dataclass(frozen=True)
class Anchor:
    """The event the next cycle counts from.

    `service`: a line item's visit (date, odometer, hours as recorded there).
    `completion`: a reminder marked done without a service record.
    `baseline`: no history; today's date and the current readings, stored once.
    """

    kind: AnchorKind
    date: date
    odometer_km: Decimal | None = None
    hours: Decimal | None = None
    line_item_id: int | None = None


@dataclass(frozen=True)
class Thresholds:
    """The due targets a reminder carries, plus the reminder type they imply."""

    due_date: date | None
    due_mileage_km: Decimal | None
    due_hours: Decimal | None
    reminder_type: str


def has_time_interval(rule: HasIntervals) -> bool:
    """Whether the rule sets any calendar interval."""
    return bool(rule.interval_months) or bool(rule.interval_days)


def add_interval(start: date, months: int | None, days: int | None) -> date:
    """`start` plus calendar months (month-end clamped) plus days.

    2026-06-13 + 6 months = 2026-12-13. 2026-08-31 + 6 months = 2027-02-28.
    """
    result = start
    if months:
        result = result + relativedelta(months=months)
    if days:
        result = result + timedelta(days=days)
    return result


def reminder_type_for(
    due_date: date | None, due_mileage_km: Decimal | None, due_hours: Decimal | None
) -> str | None:
    """The reminder type that holds exactly these thresholds.

    `smart` is date plus one usage target (`validate_reminder_state` allows
    exactly one of mileage/hours with it), which is what a rule with a
    calendar interval and a usage interval produces. `both` is never
    generated: it is the legacy hand-made date+mileage shape.
    """
    if due_date is not None and (due_mileage_km is not None or due_hours is not None):
        return "smart"
    if due_date is not None:
        return "date"
    if due_mileage_km is not None:
        return "mileage"
    if due_hours is not None:
        return "hours"
    return None


def next_thresholds(rule: HasIntervals, anchor: Anchor) -> Thresholds | None:
    """The thresholds `rule` produces from `anchor`, or `None` if it produces none.

    A usage interval whose anchor lacks that reading is dropped, not guessed:
    a rule of 8,000 km anchored on a visit with no odometer yields only its
    date threshold. When nothing remains (a mileage-only rule on such a visit)
    there is no reminder to write, and the caller reports why.
    """
    due_date: date | None = None
    if has_time_interval(rule):
        due_date = add_interval(anchor.date, rule.interval_months, rule.interval_days)

    due_mileage_km: Decimal | None = None
    if rule.interval_km is not None and anchor.odometer_km is not None:
        due_mileage_km = (Decimal(anchor.odometer_km) + Decimal(rule.interval_km)).quantize(
            KM_QUANTUM, rounding=ROUND_HALF_UP
        )

    due_hours: Decimal | None = None
    if rule.interval_hours is not None and anchor.hours is not None:
        due_hours = (Decimal(anchor.hours) + Decimal(rule.interval_hours)).quantize(
            HOURS_QUANTUM, rounding=ROUND_HALF_UP
        )

    reminder_type = reminder_type_for(due_date, due_mileage_km, due_hours)
    if reminder_type is None:
        return None
    return Thresholds(due_date, due_mileage_km, due_hours, reminder_type)


def project_usage_date(
    current: Decimal, target: Decimal, rate_per_day: float, today: date
) -> date | None:
    """When `target` is reached at `rate_per_day`, uncapped.

    `today` when the target is already met; `None` without a positive rate, or
    when the rate is so slow the date would land past the calendar.
    Unlike `reminder_service.calculate_smart_estimated_date`, this is NOT
    capped at the reminder's date threshold: the cap is what fused "when will
    I hit the mileage" with "when is it due", and the UI now shows the two
    apart.
    """
    if rate_per_day <= 0:
        return None
    if target <= current:
        return today
    days = float(target - current) / rate_per_day
    # A near-zero rate projects past the calendar; that is "can't project",
    # not a date (and `today + timedelta` would raise OverflowError).
    if not math.isfinite(days) or days > (date.max - today).days:
        return None
    return today + timedelta(days=days)

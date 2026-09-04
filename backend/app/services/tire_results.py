"""Typed results for tire distance and wear.

Both calculations used to answer `Decimal | None`, and the null carried no
reason. A caller then had to distinguish "no mount recorded", "a period is
missing an odometer bound", "the odometer went backwards", "this tire has only
ever been a spare" and "this figure came from the legacy raw-delta path" from a
single `None` -- information the return type had already thrown away. The
result was that every null rendered as one message, usually the wrong one, and
the analytics surface was pushed toward re-implementing the calculation.

The statuses are EXHAUSTIVE and every caller handles every member. A caller
that falls through on one renders a silent zero, which for a tire means telling
someone their tread is fine.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum


class DistanceStatus(StrEnum):
    """Why `distance_on_tire` did or did not produce an all-time figure."""

    #: Every period has both odometer bounds. `all_time_value` is the answer.
    COMPLETE = "complete"
    #: Some periods are bounded and some are not. `known_value` is the part
    #: that IS measurable; the all-time total is withheld.
    INCOMPLETE = "incomplete"
    #: Periods exist but NONE has both bounds, so there is no subtotal either.
    #: This is the state of every tire migrated by 097 on upgrade day, because
    #: the assumed period it creates has a null start odometer. It is the
    #: common case, not an edge one, and it must never render as "0 km".
    NOTHING_BOUNDED = "nothing_bounded"
    #: No mount period recorded at all.
    NO_PERIODS = "no_periods"
    #: Every period is at SPARE. The tire has never rolled, which is a state
    #: rather than a measurement of zero.
    SPARE_ONLY = "spare_only"
    #: A period ends below where it started. A data fault, not a gap: the
    #: repair is to correct a number, not to supply a missing one.
    ODOMETER_ROLLBACK = "odometer_rollback"


class WearStatus(StrEnum):
    """Why `project_wear` did or did not produce a projection."""

    #: Two bounded readings on a period-aware distance.
    PROJECTED = "projected"
    #: Already at or past the replacement threshold. Replace now.
    AT_OR_BELOW_MINIMUM = "at_or_below_minimum"
    #: `min_tread_mm` is null. There is NO 2.0 fallback: the 2.0 is a column
    #: default that applies at insert, not to a row already holding null.
    NO_MINIMUM_SET = "no_minimum_set"
    #: Fewer than two tread-bearing readings. One reading is a point.
    INSUFFICIENT_READINGS = "insufficient_readings"
    #: The readings carry no odometer, so there is no distance to wear against.
    NO_READING_ODOMETERS = "no_reading_odometers"
    #: Tread flat or increasing between the two readings, so no wear rate
    #: exists. Distinct from NO_DISTANCE_ON_TIRE: "your tread is not going
    #: down" and "you have not driven on this tire" need different prompts,
    #: and the pre-v3.3.0 code could not tell a caller which had happened.
    TREAD_NOT_DECREASING = "tread_not_decreasing"
    #: Distance on this tire is unavailable, so there is no denominator.
    NO_DISTANCE_ON_TIRE = "no_distance_on_tire"
    #: Would have come from the legacy raw-delta path, which treats the whole
    #: odometer span between two readings as distance driven on THIS tire.
    #: For a two-set owner that is wrong by the distance driven on the other
    #: set, erring high -- the dangerous direction for a tire. Suppressed, not
    #: labelled: an "estimate" badge does not communicate that 648,000 km is
    #: structurally invalid rather than merely imprecise.
    UNVERIFIED_MOUNT_HISTORY = "unverified_mount_history"


@dataclass(frozen=True)
class DistanceResult:
    """Distance driven on one tire, with the reason when it is unknown."""

    status: DistanceStatus
    #: Total across every period. Non-null only when status is COMPLETE.
    all_time_value: Decimal | None = None
    #: Sum over the periods that DO have both bounds. Non-null for COMPLETE
    #: and INCOMPLETE. This is the field that stops a migrated tire from
    #: reporting nothing forever once part of its history becomes measurable.
    known_value: Decimal | None = None
    #: `mounted_on` of the earliest period contributing to `known_value`.
    #: Only ever taken from a period that actually contributed, so an assumed
    #: period's null start cannot poison it.
    known_since: dt.date | None = None
    #: Periods the user must act on. Populated for INCOMPLETE (missing bounds)
    #: and ODOMETER_ROLLBACK (a faulted period); the STATUS says which kind.
    blocking_period_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class WearResult:
    """A wear projection, with the reason when there is none.

    Carries TWO values, not one. `_project_wear` has always returned
    `(km_remaining, wear_date)` and both are on the wire as
    `projected_km_remaining` and `projected_wear_date`, rendered together by
    the tire card. A single-value result type would have silently deleted the
    date from the API.
    """

    status: WearStatus
    km_remaining: Decimal | None = None
    #: Null even on a successful projection when the two readings are same-day
    #: (`day_delta == 0`) or the derived rate is non-positive. So it is not a
    #: proxy for "did this project": read `status` for that.
    wear_date: dt.date | None = None
    blocking_period_ids: list[int] = field(default_factory=list)

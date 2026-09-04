"""Tire readiness: how many tires can answer each question, and what is missing.

This is the block spec B leads with, and it exists because of a measurement
rather than a preference. On the instance that asked for tire analytics there
were two tires, two readings, and **zero** readings carrying an odometer, so
every analytical block would have rendered empty. A page whose job is to
display tire data has to first help you produce some.

The three requirements are INDEPENDENT and are counted independently here.
`project_wear` cannot supply them: it short-circuits in a fixed order, so a
tire missing both a minimum tread and its reading odometers reports only
`no_minimum_set`, and a readiness block built from that status would tell the
user about one problem and hide the other.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.schemas.analytics import TireReadiness
from app.schemas.tire import TireReadingResponse, TireResponse
from app.services.tire_results import DistanceStatus, WearStatus

#: Distance statuses that a MOUNT ODOMETER would fix. `spare_only` is a state
#: rather than a gap (the tire has never rolled) and `odometer_rollback` is bad
#: data whose repair is to correct a number, not to supply a missing one.
#: Prompting for a mount odometer on either would be advice about the wrong
#: thing.
_DISTANCE_NEEDS_ODOMETER = frozenset(
    {
        DistanceStatus.NO_PERIODS,
        DistanceStatus.NOTHING_BOUNDED,
        DistanceStatus.INCOMPLETE,
    }
)

_WEAR_HAS_FIGURE = frozenset({WearStatus.PROJECTED, WearStatus.AT_OR_BELOW_MINIMUM})


def _tread_bearing(tire: TireResponse) -> list[TireReadingResponse]:
    """Readings that carry a tread depth, newest first.

    Same selection `project_wear` makes (`tire_service.py`): sorted by
    `recorded_at` descending, then filtered to those with a tread. Kept in step
    by a test that seeds a tire missing only its reading odometers and asserts
    both this count and `wear_status` agree about it.
    """
    return sorted(
        [r for r in (tire.readings or []) if r.tread_depth_mm is not None],
        key=lambda r: r.recorded_at,
        reverse=True,
    )


def tire_readiness(tires: Sequence[TireResponse]) -> TireReadiness:
    """Count what this vehicle's live tires can and cannot answer.

    Retired tires are excluded from every count (B10). Their distance and wear
    are the most complete data the app will ever hold, so they belong in the
    history blocks, but telling someone to add an odometer reading to a tire in
    a landfill is noise.

    Args:
        tires: Every tire for the vehicle, retired ones included.

    Returns:
        The counts, over non-retired tires only.
    """
    live = [tire for tire in tires if tire.retired_on is None]

    can_trend = 0
    needs_second_reading = 0
    needs_reading_odometer = 0
    for tire in live:
        readings = _tread_bearing(tire)
        if len(readings) < 2:
            needs_second_reading += 1
            continue
        can_trend += 1
        # The newest two are the pair `project_wear` differences, so those are
        # the two whose odometers matter. A third, older reading without one
        # costs nothing.
        if readings[0].odometer_km is None or readings[1].odometer_km is None:
            needs_reading_odometer += 1

    return TireReadiness(
        total=len(live),
        can_trend=can_trend,
        can_project=sum(1 for t in live if t.wear_status in _WEAR_HAS_FIGURE),
        can_report_distance=sum(1 for t in live if t.distance_status == DistanceStatus.COMPLETE),
        under_minimum=sum(1 for t in live if t.below_threshold),
        needs_second_reading=needs_second_reading,
        needs_reading_odometer=needs_reading_odometer,
        needs_minimum_tread=sum(1 for t in live if t.min_tread_mm is None),
        needs_mount_odometer=sum(1 for t in live if t.distance_status in _DISTANCE_NEEDS_ODOMETER),
    )

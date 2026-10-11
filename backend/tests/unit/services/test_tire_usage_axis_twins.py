"""Each tire figure is one rule on both axes (#217).

A distance tire and its hours twin carry the same numbers, one in the odometer
columns and one in the hour columns, with the other columns empty. Every
function must give both the same answer, and the expected one. An axis that
reads the wrong column sees empty bounds and answers differently.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

import pytest

from app.models.tire import Tire, TireMountPeriod, TireReading
from app.services.tire_history import validate_period_history
from app.services.tire_results import DistanceStatus, IntervalStatus, WearStatus
from app.services.tire_service import distance_between, distance_on_tire, project_wear
from app.services.usage_axis import DISTANCE, HOURS, UsageAxis

D = dt.date


def _n(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


@dataclass(frozen=True)
class P:
    pid: int
    start: str | None
    end: str | None = None
    mounted_on: dt.date | None = D(2026, 1, 1)
    dismounted_on: dt.date | None = None
    position: str = "FL"


@dataclass(frozen=True)
class R:
    rid: int
    day: dt.date
    at: str | None
    tread: str | None = None


def _tire(axis: UsageAxis, periods: list[P], readings: tuple[R, ...] = ()) -> Tire:
    tire = Tire(vin="V" * 17, position="FL", min_tread_mm=Decimal("2.0"))
    built = []
    for p in periods:
        period = TireMountPeriod(
            position=p.position,
            mounted_on=p.mounted_on,
            dismounted_on=p.dismounted_on,
            is_assumed=False,
            observed_active_on=None,
        )
        period.id = p.pid
        if axis.is_hours:
            period.mounted_hours, period.dismounted_hours = _n(p.start), _n(p.end)
        else:
            period.mounted_odometer_km, period.dismounted_odometer_km = _n(p.start), _n(p.end)
        built.append(period)
    tire.mount_periods = built
    rows = []
    for r in readings:
        reading = TireReading(
            tire_id=1, vin="V" * 17, recorded_at=r.day, tread_depth_mm=_n(r.tread)
        )
        reading.id = r.rid
        if axis.is_hours:
            reading.engine_hours = _n(r.at)
        else:
            reading.odometer_km = _n(r.at)
        rows.append(reading)
    tire.readings = rows
    treads = [x for x in sorted(rows, key=lambda x: x.recorded_at) if x.tread_depth_mm is not None]
    tire.tread_depth_mm = treads[-1].tread_depth_mm if treads else None
    return tire


DISTANCE_SHAPES = {
    "closed": (
        [P(1, "1000", "9000", dismounted_on=D(2026, 6, 1))],
        "12000",
        DistanceStatus.COMPLETE,
        "8000",
    ),
    "open_to_current": ([P(1, "1000")], "4000", DistanceStatus.COMPLETE, "3000"),
    "one_unbounded": (
        [P(1, "1000", "2000", dismounted_on=D(2026, 3, 1)), P(2, None, mounted_on=D(2026, 4, 1))],
        "5000",
        DistanceStatus.INCOMPLETE,
        "1000",
    ),
    "rollback": (
        [P(1, "9000", "1000", dismounted_on=D(2026, 6, 1))],
        "12000",
        DistanceStatus.ODOMETER_ROLLBACK,
        None,
    ),
    "spare_only": ([P(1, "1000", position="SPARE")], "5000", DistanceStatus.SPARE_ONLY, None),
    "no_current": ([P(1, "1000")], None, DistanceStatus.NOTHING_BOUNDED, None),
}


@pytest.mark.parametrize("name", list(DISTANCE_SHAPES))
def test_distance_on_tire_twins(name):
    periods, current, status, value = DISTANCE_SHAPES[name]
    results = [
        distance_on_tire(_tire(axis, periods), _n(current), axis) for axis in (DISTANCE, HOURS)
    ]
    for result in results:
        assert result.status is status
        known = result.known_value if status is DistanceStatus.INCOMPLETE else result.all_time_value
        assert known == _n(value)
    assert results[0].blocking_period_ids == results[1].blocking_period_ids


SEASONAL = [
    P(1, "1000", "4000", mounted_on=D(2026, 1, 1), dismounted_on=D(2026, 4, 1)),
    P(2, "8000", mounted_on=D(2026, 8, 1)),
]
INTERVAL_SHAPES = {
    # 2000..4000 on the first set, 8000..9000 on the second: 3000, not 7000.
    "seasonal": (
        SEASONAL,
        (R(1, D(2026, 3, 1), "2000"), R(2, D(2026, 9, 1), "9000")),
        "9500",
        IntervalStatus.COMPLETE,
        "3000",
    ),
    "overlapping": (
        [
            P(1, "1000", "5000", mounted_on=D(2026, 1, 1), dismounted_on=D(2026, 6, 1)),
            P(2, "4000", mounted_on=D(2026, 3, 1)),
        ],
        (R(1, D(2026, 2, 1), "2000"), R(2, D(2026, 7, 1), "6000")),
        "6000",
        IntervalStatus.OVERLAPPING_HISTORY,
        None,
    ),
    "contradicts": (
        [P(1, "1000", "5000", mounted_on=D(2026, 1, 1), dismounted_on=D(2026, 5, 1))],
        (R(1, D(2026, 2, 1), "2000"), R(2, D(2026, 6, 1), "4000")),
        "5000",
        IntervalStatus.HISTORY_CONTRADICTS,
        None,
    ),
    "unverified": (
        [P(1, None)],
        (R(1, D(2026, 2, 1), "2000"), R(2, D(2026, 3, 1), "3000")),
        "3000",
        IntervalStatus.UNVERIFIED,
        None,
    ),
}


@pytest.mark.parametrize("name", list(INTERVAL_SHAPES))
def test_distance_between_twins(name):
    periods, readings, current, status, value = INTERVAL_SHAPES[name]
    results = []
    for axis in (DISTANCE, HOURS):
        tire = _tire(axis, periods, readings)
        older, newer = sorted(tire.readings, key=lambda r: r.recorded_at)
        results.append(distance_between(tire, older, newer, _n(current), axis))
    for result in results:
        assert result.status is status
        assert result.km == _n(value)
    assert results[0].blocking_period_ids == results[1].blocking_period_ids


def test_project_wear_twins():
    # Tread 8.0 -> 7.0 over 50 units, 2.0 minimum: 5 mm left at 1 mm per 50 = 250.
    periods = [P(1, "90")]
    readings = (R(1, D(2026, 1, 1), "100", "8.0"), R(2, D(2026, 1, 11), "150", "7.0"))
    for axis in (DISTANCE, HOURS):
        result = project_wear(_tire(axis, periods, readings), Decimal("150"), axis=axis)
        assert result.status is WearStatus.PROJECTED
        assert result.km_remaining == Decimal("250.0")
        # 50 units over 10 days is 5 a day, so 50 days past the newer reading.
        assert result.wear_date == D(2026, 3, 2)


def test_project_wear_needs_the_axis_reading():
    periods = [P(1, "90")]
    readings = (R(1, D(2026, 1, 1), None, "8.0"), R(2, D(2026, 1, 11), None, "7.0"))
    for axis in (DISTANCE, HOURS):
        result = project_wear(_tire(axis, periods, readings), Decimal("150"), axis=axis)
        assert result.status is WearStatus.NO_READING_ODOMETERS


def test_the_overlap_check_uses_the_axis_band():
    # 0.03 of overlap: beyond the km band at 100 (about 0.0103), inside the hours band (0.05).
    periods = [
        P(1, "0", "100.03", mounted_on=D(2026, 1, 1), dismounted_on=D(2026, 2, 1)),
        P(2, "100.00", mounted_on=D(2026, 2, 1)),
    ]
    readings = (R(1, D(2026, 1, 2), "50"), R(2, D(2026, 3, 1), "150"))
    hours_tire = _tire(HOURS, periods, readings)
    older, newer = sorted(hours_tire.readings, key=lambda r: r.recorded_at)
    assert (
        distance_between(hours_tire, older, newer, Decimal("150"), HOURS).status
        is IntervalStatus.COMPLETE
    )
    km_tire = _tire(DISTANCE, periods, readings)
    older, newer = sorted(km_tire.readings, key=lambda r: r.recorded_at)
    assert (
        distance_between(km_tire, older, newer, Decimal("150"), DISTANCE).status
        is IntervalStatus.OVERLAPPING_HISTORY
    )


HISTORY_SHAPES = {
    "reversed": ([P(1, "9000", "1000", dismounted_on=D(2026, 6, 1))], (), "reversed"),
    "mounted_below_earlier_dismount": (
        [
            P(1, "1000", "5000", mounted_on=D(2026, 1, 1), dismounted_on=D(2026, 3, 1)),
            P(2, "4000", mounted_on=D(2026, 4, 1)),
        ],
        (),
        "overlapping",
    ),
    "reading_runs_backwards": (
        [P(1, "1000", "5000", mounted_on=D(2026, 1, 1), dismounted_on=D(2026, 5, 1))],
        (R(1, D(2026, 6, 1), "4000"),),
        "contradicts",
    ),
}


@pytest.mark.parametrize("name", list(HISTORY_SHAPES))
def test_history_twins(name):
    periods, readings, kind = HISTORY_SHAPES[name]
    by_axis = {}
    for axis in (DISTANCE, HOURS):
        faults = validate_period_history(
            _tire(axis, periods, readings).mount_periods,
            _tire(axis, periods, readings).readings,
            axes=(axis,),
        )
        by_axis[axis.kind] = faults
        expected = {
            "reversed": axis.reversed_code,
            "overlapping": axis.overlapping_code,
            "contradicts": axis.contradicts_code,
        }[kind]
        assert expected in {f.code for f in faults}
    assert [(f.period_id, f.counterpart_id) for f in by_axis["distance"]] == [
        (f.period_id, f.counterpart_id) for f in by_axis["hours"]
    ]
    assert all("hr" in f.message for f in by_axis["hours"])

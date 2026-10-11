"""The history rules on the hour meter, and on two axes at once (#217)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.models.tire import TireMountPeriod, TireReading
from app.services.tire_history import (
    OVERLAPPING_DATES,
    REVERSED_ODOMETER,
    validate_period_history,
)
from app.services.usage_axis import DISTANCE, HOURS


def _period(pid: int, **kw) -> TireMountPeriod:
    defaults = dict(position="FL", mounted_on=dt.date(2026, 1, 1), is_assumed=False)
    defaults.update(kw)
    period = TireMountPeriod(**defaults)
    period.id = pid
    return period


def test_a_reversed_hour_meter_reads_as_hours():
    p = _period(
        1,
        dismounted_on=dt.date(2026, 6, 1),
        mounted_hours=Decimal("150.0"),
        dismounted_hours=Decimal("120.0"),
    )
    [fault] = validate_period_history([p], [], axes=(HOURS,))
    assert fault.code == "reversed_hours"
    assert fault.message == (
        "The FL period mounted 2026-01-01 is dismounted at 120.0 hr, below its mount hours of 150.0 hr."
    )


def test_a_reading_that_runs_the_hour_meter_backwards():
    p = _period(
        1,
        dismounted_on=dt.date(2026, 5, 1),
        mounted_hours=Decimal("100.0"),
        dismounted_hours=Decimal("200.0"),
    )
    r = TireReading(
        tire_id=1, vin="V" * 17, recorded_at=dt.date(2026, 6, 1), engine_hours=Decimal("150.0")
    )
    r.id = 7
    [fault] = validate_period_history([p], [r], axes=(HOURS,))
    assert fault.code == "contradicts_reading_hours"
    assert "the vehicle's hour meter would have to run backwards" in fault.message


def test_two_spans_claiming_the_same_hours():
    # An unknown mount date keeps 4a out of it, so only the order-free check sees the overlap.
    first = _period(
        1,
        dismounted_on=dt.date(2026, 2, 1),
        mounted_hours=Decimal("100.0"),
        dismounted_hours=Decimal("200.0"),
    )
    second = _period(
        2,
        mounted_on=None,
        dismounted_on=dt.date(2026, 3, 1),
        mounted_hours=Decimal("150.0"),
        dismounted_hours=Decimal("250.0"),
    )
    [fault] = validate_period_history([first, second], [], axes=(HOURS,))
    assert (fault.period_id, fault.code, fault.counterpart_id) == (2, "overlapping_hours", 1)
    assert fault.message == (
        "The FL period with an unknown mount date claims hours the FL period mounted 2026-01-01 "
        "already covers: it starts at 150.0 hr, before that period ended at 200.0 hr."
    )


def test_dual_axes_check_both_and_the_dates_once():
    # Reversed on hours only, and its dates overlap an earlier open period.
    earlier = _period(1, mounted_odometer_km=Decimal("1000"), mounted_hours=Decimal("10.0"))
    later = _period(
        2,
        mounted_on=dt.date(2026, 2, 1),
        dismounted_on=dt.date(2026, 3, 1),
        mounted_odometer_km=Decimal("2000"),
        dismounted_odometer_km=Decimal("3000"),
        mounted_hours=Decimal("50.0"),
        dismounted_hours=Decimal("40.0"),
    )
    faults = validate_period_history([earlier, later], [], axes=(DISTANCE, HOURS))
    codes = [f.code for f in faults]
    assert codes.count(OVERLAPPING_DATES) == 1
    assert "reversed_hours" in codes
    assert REVERSED_ODOMETER not in codes


def test_no_axes_means_distance_alone():
    p = _period(
        1,
        dismounted_on=dt.date(2026, 6, 1),
        mounted_hours=Decimal("150.0"),
        dismounted_hours=Decimal("120.0"),
    )
    assert validate_period_history([p], []) == []

"""`UsageAxis` and `VehicleAxes` (#217): one rule set, two columns."""

import datetime as dt
from decimal import Decimal

import pytest

from app.models.tire import TireMountPeriod, TireReading
from app.services import tire_history
from app.services.usage_axis import DISTANCE, HOURS, VehicleAxes, format_km


def _period() -> TireMountPeriod:
    return TireMountPeriod(
        position="FL",
        mounted_on=dt.date(2026, 1, 1),
        mounted_odometer_km=Decimal("1000.00"),
        dismounted_odometer_km=Decimal("2000.00"),
        mounted_hours=Decimal("10.0"),
        dismounted_hours=Decimal("20.0"),
        is_assumed=False,
    )


def _reading() -> TireReading:
    return TireReading(
        tire_id=1,
        vin="V" * 17,
        recorded_at=dt.date(2026, 2, 1),
        odometer_km=Decimal("1500.00"),
        engine_hours=Decimal("15.0"),
    )


def test_each_axis_reads_its_own_columns():
    p, r = _period(), _reading()
    assert (DISTANCE.mounted(p), DISTANCE.dismounted(p), DISTANCE.reading(r)) == (
        Decimal("1000.00"),
        Decimal("2000.00"),
        Decimal("1500.00"),
    )
    assert (HOURS.mounted(p), HOURS.dismounted(p), HOURS.reading(r)) == (
        Decimal("10.0"),
        Decimal("20.0"),
        Decimal("15.0"),
    )


def test_each_axis_compares_with_its_own_band():
    # 0.04 apart: beyond the km band at 100 (about 0.0103), inside the hours band (0.05).
    a, b = Decimal("100.00"), Decimal("100.04")
    assert DISTANCE.below(a, b) is True
    assert HOURS.below(a, b) is False
    assert DISTANCE.above(b, a) is True
    assert HOURS.above(b, a) is False


def test_a_zero_carries_the_column_scale():
    assert str(DISTANCE.zero) == "0.00"
    assert str(HOURS.zero) == "0.0"


def test_the_distance_codes_are_the_ones_on_the_wire_today():
    assert DISTANCE.reversed_code == tire_history.REVERSED_ODOMETER
    assert DISTANCE.overlapping_code == tire_history.OVERLAPPING_ODOMETER
    assert DISTANCE.contradicts_code == tire_history.CONTRADICTS_READING


def test_the_hours_codes_are_their_own():
    hours = {HOURS.reversed_code, HOURS.overlapping_code, HOURS.contradicts_code}
    distance = {DISTANCE.reversed_code, DISTANCE.overlapping_code, DISTANCE.contradicts_code}
    assert hours == {"reversed_hours", "overlapping_hours", "contradicts_reading_hours"}
    assert not hours & distance


def test_messages_name_the_right_meter():
    assert (DISTANCE.meter, DISTANCE.mount_reading, DISTANCE.quantity) == (
        "odometer",
        "mount odometer",
        "distance",
    )
    assert (HOURS.meter, HOURS.mount_reading, HOURS.quantity) == (
        "hour meter",
        "mount hours",
        "hours",
    )
    assert DISTANCE.fmt(Decimal("12000.50")) == "12,000.5 km"
    assert HOURS.fmt(Decimal("1234.5")) == "1,234.5 hr"


def test_with_fmt_swaps_only_the_formatter():
    swapped = DISTANCE.with_fmt(lambda v: f"{v} mi")
    assert swapped.kind == "distance"
    assert swapped.fmt(Decimal("1")) == "1 mi"
    assert DISTANCE.fmt is format_km


@pytest.mark.parametrize(
    ("usage_unit", "secondary", "primary", "captured"),
    [
        ("distance", False, "distance", ("distance",)),
        ("hours", False, "hours", ("hours",)),
        ("hours", True, "distance", ("distance", "hours")),
        ("distance", True, "distance", ("distance", "hours")),
        (None, None, "distance", ("distance",)),
    ],
)
def test_vehicle_axes(usage_unit, secondary, primary, captured):
    axes = VehicleAxes.for_vehicle(usage_unit, secondary)
    assert axes.primary.kind == primary
    assert tuple(a.kind for a in axes.captured) == captured
    assert axes.tracks("distance") is ("distance" in captured)
    assert axes.tracks("hours") is ("hours" in captured)


def test_the_distance_axis_renders_in_the_callers_unit():
    axes = VehicleAxes.for_vehicle("distance", False, lambda v: f"{v} mi")
    assert axes.primary.fmt(Decimal("5")) == "5 mi"
    assert VehicleAxes.distance_only().captured == (DISTANCE,)


def test_tire_history_still_exports_the_formatter():
    assert tire_history.format_km is format_km
    assert tire_history.distance_formatter is not None

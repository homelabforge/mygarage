"""Field-name/nullability contract tests for the hours-usage-model Task 7
analytics response schemas.

Locks the exact wire shape of the new hours-native analytics series
(``HoursEconomyDataPoint`` / ``HoursEconomyTrend`` / ``HoursAccumulatedDataPoint``)
mirroring the existing distance shapes (``FuelEconomyDataPoint`` /
``FuelEconomyTrend``), so a later refactor can't silently rename or drop a
field the frontend depends on.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.analytics import (
    HoursAccumulatedDataPoint,
    HoursEconomyDataPoint,
    HoursEconomyTrend,
    VehicleAnalytics,
)


def test_hours_economy_data_point_field_names_and_nullability():
    point = HoursEconomyDataPoint(
        date=date(2026, 1, 1),
        engine_hours=Decimal("120.0"),
        l_per_hr=None,
        cost_per_hr=Decimal("0.75"),
        liters=Decimal("0.000"),
        cost=Decimal("15.00"),
    )
    dumped = point.model_dump()

    assert set(dumped.keys()) == {
        "date",
        "engine_hours",
        "l_per_hr",
        "cost_per_hr",
        "liters",
        "cost",
    }
    # l_per_hr is nullable (zero-liters convention); the rest are not.
    assert dumped["l_per_hr"] is None
    assert dumped["cost_per_hr"] == Decimal("0.75")


def test_hours_economy_data_point_l_per_hr_defaults_to_none():
    """l_per_hr has a default of None -- callers aren't forced to pass it."""
    point = HoursEconomyDataPoint(
        date=date(2026, 1, 1),
        engine_hours=Decimal("100.0"),
        cost_per_hr=Decimal("1.00"),
        liters=Decimal("10.000"),
        cost=Decimal("10.00"),
    )
    assert point.l_per_hr is None


def test_hours_economy_data_point_requires_cost_per_hr():
    """Unlike l_per_hr, cost_per_hr has no default -- a point that exists in
    the series always has a real cost_per_hr figure."""
    with pytest.raises(ValidationError):
        HoursEconomyDataPoint.model_validate(
            {
                "date": date(2026, 1, 1),
                "engine_hours": Decimal("100.0"),
                "liters": Decimal("10.000"),
                "cost": Decimal("10.00"),
            }
        )


def test_hours_economy_trend_defaults_are_null_and_empty():
    """A pure-distance vehicle gets this exact shape: every scalar null, the
    trend marker its literal default, and an empty data_points list --
    'null/empty', never an omitted object."""
    trend = HoursEconomyTrend()

    assert trend.model_dump() == {
        "average_l_per_hr": None,
        "average_cost_per_hr": None,
        "best_l_per_hr": None,
        "worst_l_per_hr": None,
        "recent_l_per_hr": None,
        "recent_cost_per_hr": None,
        "trend": "stable",
        "data_points": [],
    }


def test_hours_accumulated_data_point_field_names_and_required():
    point = HoursAccumulatedDataPoint(date=date(2026, 1, 1), engine_hours=Decimal("42.5"))

    assert point.model_dump() == {
        "date": date(2026, 1, 1),
        "engine_hours": Decimal("42.5"),
        "source": "manual",
    }

    with pytest.raises(ValidationError):
        HoursAccumulatedDataPoint.model_validate(
            {"date": date(2026, 1, 1)}
        )  # engine_hours is required

    with pytest.raises(ValidationError):
        HoursAccumulatedDataPoint.model_validate(
            {"engine_hours": Decimal("1.0")}
        )  # date is required


def test_vehicle_analytics_exposes_hours_economy_and_accumulated_fields():
    """VehicleAnalytics carries hours_economy (required, object-always-present
    like fuel_economy) and hours_accumulated (list, defaults empty)."""
    fields = VehicleAnalytics.model_fields

    assert "hours_economy" in fields
    assert fields["hours_economy"].annotation is HoursEconomyTrend
    assert fields["hours_economy"].is_required(), (
        "hours_economy must always be supplied by the route, mirroring fuel_economy"
    )

    assert "hours_accumulated" in fields
    assert not fields["hours_accumulated"].is_required()
    assert fields["hours_accumulated"].default == []

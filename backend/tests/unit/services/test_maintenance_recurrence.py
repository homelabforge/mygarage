"""Recurrence arithmetic: anchor + intervals, each threshold on its own.

The numbers are the ones from the report that motivated the change: an oil
service on 2026-06-13 at 88,896 mi (143,064.28 km with the exact factor),
a rule of 7,500 mi (12,070.08 km) or 6 months, due at 96,396 mi or on
2026-12-13, whichever comes first.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from app.services.maintenance_recurrence import (
    Anchor,
    add_interval,
    next_thresholds,
    project_usage_date,
    reminder_type_for,
)

MILE = Decimal("1.609344")
SERVICE_DATE = date(2026, 6, 13)
SERVICE_KM = (Decimal(88896) * MILE).quantize(Decimal("0.01"))  # 143064.28
INTERVAL_KM = (Decimal(7500) * MILE).quantize(Decimal("0.01"))  # 12070.08


@dataclass
class Rule:
    interval_km: Decimal | None = None
    interval_months: int | None = None
    interval_days: int | None = None
    interval_hours: Decimal | None = None


@pytest.mark.unit
class TestAddInterval:
    def test_six_months_from_june_13(self):
        assert add_interval(SERVICE_DATE, 6, None) == date(2026, 12, 13)

    def test_month_end_clamps(self):
        assert add_interval(date(2026, 8, 31), 6, None) == date(2027, 2, 28)
        assert add_interval(date(2026, 1, 31), 1, None) == date(2026, 2, 28)

    def test_days_add_after_months(self):
        assert add_interval(date(2026, 1, 31), 1, 1) == date(2026, 3, 1)

    def test_days_only(self):
        assert add_interval(date(2026, 6, 13), None, 30) == date(2026, 7, 13)


@pytest.mark.unit
class TestNextThresholds:
    def test_mileage_and_time_rule_from_service(self):
        anchor = Anchor("service", SERVICE_DATE, SERVICE_KM, None, line_item_id=60)
        got = next_thresholds(Rule(interval_km=INTERVAL_KM, interval_months=6), anchor)
        assert got is not None
        assert got.due_date == date(2026, 12, 13)
        assert got.due_mileage_km == Decimal("155134.32")
        # 96,396 mi, to the mile (each leg is rounded to 0.01 km on its own).
        assert (got.due_mileage_km / MILE).quantize(Decimal("1")) == Decimal("96396")
        assert got.due_hours is None
        assert got.reminder_type == "smart"

    def test_mileage_only(self):
        got = next_thresholds(
            Rule(interval_km=Decimal("8000")), Anchor("baseline", SERVICE_DATE, Decimal("1000"))
        )
        assert got is not None
        assert got.due_date is None
        assert got.due_mileage_km == Decimal("9000.00")
        assert got.reminder_type == "mileage"

    def test_time_only(self):
        got = next_thresholds(Rule(interval_days=30), Anchor("baseline", SERVICE_DATE))
        assert got is not None
        assert got == got.__class__(date(2026, 7, 13), None, None, "date")

    def test_hours_and_time(self):
        got = next_thresholds(
            Rule(interval_hours=Decimal("50"), interval_months=12),
            Anchor("service", SERVICE_DATE, None, Decimal("812.4")),
        )
        assert got is not None
        assert got.due_hours == Decimal("862.4")
        assert got.due_mileage_km is None
        assert got.reminder_type == "smart"

    def test_missing_reading_drops_that_threshold_only(self):
        got = next_thresholds(
            Rule(interval_km=Decimal("8000"), interval_months=6),
            Anchor("service", SERVICE_DATE, None, None),
        )
        assert got is not None
        assert got.due_mileage_km is None
        assert got.due_date == date(2026, 12, 13)
        assert got.reminder_type == "date"

    def test_nothing_computable_is_none(self):
        assert (
            next_thresholds(Rule(interval_km=Decimal("8000")), Anchor("service", SERVICE_DATE))
            is None
        )

    def test_quantises_to_column_steps(self):
        got = next_thresholds(
            Rule(interval_km=Decimal("0.005"), interval_hours=None),
            Anchor("baseline", SERVICE_DATE, Decimal("10")),
        )
        assert got is not None
        assert got.due_mileage_km == Decimal("10.01")


@pytest.mark.unit
class TestReminderTypeFor:
    @pytest.mark.parametrize(
        ("due_date", "km", "hours", "expected"),
        [
            (date(2026, 1, 1), Decimal(1), None, "smart"),
            (date(2026, 1, 1), None, Decimal(1), "smart"),
            (date(2026, 1, 1), None, None, "date"),
            (None, Decimal(1), None, "mileage"),
            (None, None, Decimal(1), "hours"),
            (None, None, None, None),
        ],
    )
    def test_table(self, due_date, km, hours, expected):
        assert reminder_type_for(due_date, km, hours) == expected


@pytest.mark.unit
class TestProjectUsageDate:
    def test_is_not_capped_by_any_date(self):
        # 12,000 km to go at 40 km/day is 300 days out: the projection says so
        # even though a 6-month rule would be due long before.
        today = date(2026, 9, 16)
        got = project_usage_date(Decimal("143064"), Decimal("155134"), 40.23, today)
        assert got is not None
        assert got > date(2027, 6, 1)

    def test_target_met_is_today(self):
        today = date(2026, 9, 16)
        assert project_usage_date(Decimal("10"), Decimal("10"), 5.0, today) == today

    def test_no_rate_is_none(self):
        assert project_usage_date(Decimal("1"), Decimal("2"), 0.0, date(2026, 9, 16)) is None

    def test_in_range_projection_is_a_date(self):
        # 100 km at 1 km/day: the control for the overflow cases below.
        today = date(2026, 10, 10)
        assert project_usage_date(Decimal("0"), Decimal("100"), 1.0, today) == date(2027, 1, 18)

    @pytest.mark.parametrize(
        "target, rate",
        [
            # Two readings 0.01 km apart across 89 days drive about this slow.
            (Decimal("5000"), 0.0001),
            # Small enough that the day count itself is infinite.
            (Decimal("1"), 5e-324),
        ],
        ids=["near-zero", "infinite-days"],
    )
    def test_past_the_calendar_is_none(self, target: Decimal, rate: float):
        """Past 9999-12-31 is "can't project", not an OverflowError."""
        assert project_usage_date(Decimal("0"), target, rate, date(2026, 10, 10)) is None

    def test_nan_rate_is_none(self):
        # Pins the isfinite half of the guard: NaN compares False to the day
        # bound, so without it timedelta raises ValueError.
        assert (
            project_usage_date(Decimal("0"), Decimal("1"), float("nan"), date(2026, 10, 10)) is None
        )

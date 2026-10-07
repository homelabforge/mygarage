"""The pure half of the inspection engine (#211): which schedule applies, the
theoretical cadence from the first registration, and the cycle a vehicle is
in from what is on record.

Every expected date below is a hand-written literal against the SHIPPED
profiles, so a cadence typo in a data file fails here with the country's
name in the test id.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.country_profile_service import load_profile
from app.services.inspection_schedule_service import (
    age_in_years,
    every_years_at,
    plan_cycle,
    schedule_for,
    theoretical_due_dates,
)

TODAY = date(2026, 10, 7)


def _profile(country: str):
    profile = load_profile(country)
    assert profile is not None and profile.inspection is not None, country
    return profile


def _schedule(country: str, vehicle_type: str = "Car", fuel: str | None = None):
    profile = _profile(country)
    schedule = schedule_for(profile, vehicle_type, fuel)
    assert schedule is not None, (country, vehicle_type, fuel)
    return profile, schedule


@pytest.mark.unit
class TestScheduleFor:
    def test_cars_and_motorcycles_have_their_own_schedule_in_france(self):
        profile = _profile("FR")
        car = schedule_for(profile, "Car")
        moto = schedule_for(profile, "Motorcycle")
        assert car is not None and car.steps[0].first_after_years == 4
        assert moto is not None and moto.steps[0].first_after_years == 5

    def test_a_vehicle_type_without_a_schedule_gets_none(self):
        assert schedule_for(_profile("FR"), "Boat") is None
        assert schedule_for(_profile("FR"), None) is None

    def test_the_netherlands_pick_the_grid_by_fuel(self):
        profile = _profile("NL")
        petrol = schedule_for(profile, "Car", "gasoline")
        diesel = schedule_for(profile, "Car", "diesel")
        lpg_secondary = schedule_for(profile, "Car", "gasoline", "propane_lpg")
        assert petrol is not None and petrol.steps[0].first_after_years == 4
        assert diesel is not None and diesel.steps[0].first_after_years == 3
        # A petrol car converted to LPG matches both grids; the stricter one
        # (first inspection earliest) wins, whatever the file order.
        assert lpg_secondary is not None and lpg_secondary.steps[0].first_after_years == 3

    def test_a_profile_without_inspection_rules_gets_none(self):
        profile = _profile("FR").model_copy(update={"inspection": None})
        assert schedule_for(profile, "Car") is None


@pytest.mark.unit
class TestAgeAndSteps:
    def test_age_counts_birthdays(self):
        first = date(2020, 1, 15)
        assert age_in_years(first, date(2024, 1, 14)) == 3
        assert age_in_years(first, date(2024, 1, 15)) == 4
        assert age_in_years(first, date(2026, 10, 7)) == 6

    def test_luxembourg_steps_by_age(self):
        _profile_, schedule = _schedule("LU")
        assert every_years_at(schedule, 4) == 2
        assert every_years_at(schedule, 5) == 2
        assert every_years_at(schedule, 6) == 1
        assert every_years_at(schedule, 12) == 1


@pytest.mark.unit
class TestTheoreticalDueDates:
    @pytest.mark.parametrize(
        "country,fuel,first,until,expected",
        [
            ("FR", None, date(2023, 3, 12), TODAY, [date(2027, 3, 12)]),
            (
                "FR",
                None,
                date(2015, 5, 1),
                TODAY,
                [
                    date(2019, 5, 1),
                    date(2021, 5, 1),
                    date(2023, 5, 1),
                    date(2025, 5, 1),
                    date(2027, 5, 1),
                ],
            ),
            (
                "LU",
                None,
                date(2020, 1, 15),
                date(2028, 6, 1),
                [
                    date(2024, 1, 15),
                    date(2026, 1, 15),
                    date(2027, 1, 15),
                    date(2028, 1, 15),
                    date(2029, 1, 15),
                ],
            ),
            (
                "NL",
                "gasoline",
                date(2016, 6, 1),
                date(2026, 6, 1),
                [
                    date(2020, 6, 1),
                    date(2022, 6, 1),
                    date(2024, 6, 1),
                    date(2025, 6, 1),
                    date(2026, 6, 1),
                    date(2027, 6, 1),
                ],
            ),
            (
                "NL",
                "diesel",
                date(2022, 6, 1),
                TODAY,
                [date(2025, 6, 1), date(2026, 6, 1), date(2027, 6, 1)],
            ),
            (
                "ES",
                None,
                date(2014, 9, 20),
                date(2026, 10, 7),
                [
                    date(2018, 9, 20),
                    date(2020, 9, 20),
                    date(2022, 9, 20),
                    date(2024, 9, 20),
                    date(2025, 9, 20),
                    date(2026, 9, 20),
                    date(2027, 9, 20),
                ],
            ),
            # A leap-day registration clamps to the 28th; the walk stops at
            # the first date after `until`.
            ("DE", None, date(2024, 2, 29), date(2027, 1, 1), [date(2027, 2, 28)]),
            (
                "DE",
                None,
                date(2024, 2, 29),
                date(2027, 3, 1),
                [date(2027, 2, 28), date(2029, 2, 28)],
            ),
        ],
    )
    def test_cadence(self, country, fuel, first, until, expected):
        _profile_, schedule = _schedule(country, "Car", fuel)
        assert theoretical_due_dates(schedule, first, until) == expected

    def test_the_last_date_is_always_after_until(self):
        _profile_, schedule = _schedule("BE")
        dates = theoretical_due_dates(schedule, date(1998, 4, 2), TODAY)
        assert dates[-1] > TODAY
        assert all(a < b for a, b in zip(dates, dates[1:], strict=False))


@pytest.mark.unit
class TestPlanCycle:
    def test_france_first_cycle_counts_from_the_registration(self):
        profile, schedule = _schedule("FR")
        plan = plan_cycle(profile, schedule, date(2023, 3, 12), TODAY)
        assert plan.anchor_date == date(2023, 3, 12)
        assert plan.anchor_kind == "baseline"
        assert plan.interval_months == 48
        assert plan.due_date == date(2027, 3, 12)
        assert plan.first_cycle is True
        assert plan.retest is False
        assert plan.lead_days == 180

    def test_france_later_cycle_counts_from_the_last_theoretical_due_date(self):
        profile, schedule = _schedule("FR")
        plan = plan_cycle(profile, schedule, date(2015, 5, 1), TODAY)
        assert plan.anchor_date == date(2025, 5, 1)
        assert plan.anchor_kind == "baseline"
        assert plan.interval_months == 24
        assert plan.due_date == date(2027, 5, 1)
        assert plan.first_cycle is False

    def test_a_recorded_inspection_starts_the_next_cycle_from_the_test_date(self):
        profile, schedule = _schedule("FR")
        plan = plan_cycle(
            profile, schedule, date(2015, 5, 1), TODAY, last_inspection=date(2026, 2, 10)
        )
        assert plan.anchor_date == date(2026, 2, 10)
        assert plan.anchor_kind == "service"
        assert plan.interval_months == 24
        assert plan.due_date == date(2028, 2, 10)
        assert plan.retest is False

    def test_a_failed_inspection_is_due_again_within_the_retest_window(self):
        profile, schedule = _schedule("FR")
        plan = plan_cycle(
            profile,
            schedule,
            date(2015, 5, 1),
            TODAY,
            last_inspection=date(2026, 2, 10),
            last_failed=True,
        )
        assert plan.interval_months == 2
        assert plan.due_date == date(2026, 4, 10)
        assert plan.retest is True

    def test_a_failure_without_a_retest_window_is_an_ordinary_cycle(self):
        profile, schedule = _schedule("LU")
        plan = plan_cycle(
            profile,
            schedule,
            date(2020, 1, 15),
            TODAY,
            last_inspection=date(2026, 1, 20),
            last_failed=True,
        )
        assert plan.retest is False
        assert plan.interval_months == 12
        assert plan.due_date == date(2027, 1, 20)

    def test_luxembourg_goes_yearly_from_age_six(self):
        profile, schedule = _schedule("LU")
        plan = plan_cycle(profile, schedule, date(2020, 1, 15), TODAY)
        assert plan.anchor_date == date(2026, 1, 15)
        assert plan.interval_months == 12
        assert plan.due_date == date(2027, 1, 15)
        assert plan.lead_days is None

    def test_netherlands_diesel_is_overdue_when_the_theoretical_date_passed_this_year(self):
        profile, schedule = _schedule("NL", "Car", "diesel")
        plan = plan_cycle(profile, schedule, date(2022, 6, 1), date(2026, 7, 1))
        # Dues 2025-06-01 and 2026-06-01 are past: the reminder counts from
        # 2026-06-01 and is due 2027-06-01; what the owner did about the one
        # that just passed is theirs to record.
        assert plan.anchor_date == date(2026, 6, 1)
        assert plan.due_date == date(2027, 6, 1)
        assert plan.interval_months == 12
        assert plan.lead_days == 60

    def test_spain_yearly_after_ten(self):
        profile, schedule = _schedule("ES")
        plan = plan_cycle(profile, schedule, date(2014, 9, 20), TODAY)
        assert plan.anchor_date == date(2026, 9, 20)
        assert plan.due_date == date(2027, 9, 20)
        assert plan.interval_months == 12
        assert plan.lead_days == 30

    def test_french_motorcycle_five_then_three(self):
        profile, schedule = _schedule("FR", "Motorcycle")
        plan = plan_cycle(profile, schedule, date(2020, 6, 1), TODAY)
        assert plan.anchor_date == date(2025, 6, 1)
        assert plan.due_date == date(2028, 6, 1)
        assert plan.interval_months == 36
        early = plan_cycle(profile, schedule, date(2024, 6, 1), TODAY)
        assert early.anchor_date == date(2024, 6, 1)
        assert early.due_date == date(2029, 6, 1)
        assert early.interval_months == 60
        assert early.first_cycle is True

    def test_germany_three_then_two(self):
        profile, schedule = _schedule("DE")
        plan = plan_cycle(profile, schedule, date(2024, 2, 29), TODAY)
        assert plan.due_date == date(2027, 2, 28)
        assert plan.interval_months == 36
        retest = plan_cycle(
            profile,
            schedule,
            date(2018, 1, 1),
            TODAY,
            last_inspection=date(2026, 9, 1),
            last_failed=True,
        )
        assert retest.due_date == date(2026, 10, 1)
        assert retest.interval_months == 1

"""What insurance cost over a span of days."""

from datetime import date
from decimal import Decimal

from app.utils.insurance_cost import (
    accrued_cost,
    cost_between,
    monthly_costs,
    periods_in_term,
    term_cost,
)

D = Decimal
JAN1, JUL1, NEXT_JAN1 = date(2026, 1, 1), date(2026, 7, 1), date(2027, 1, 1)


class TestPeriodsInTerm:
    def test_a_six_month_term_is_one_semi_annual_period_and_six_monthly_ones(self):
        assert periods_in_term("Semi-Annual", JAN1, JUL1) == 1
        assert periods_in_term("Monthly", JAN1, JUL1) == 6

    def test_a_year_is_twelve_months_four_quarters_one_annual(self):
        assert periods_in_term("Monthly", JAN1, NEXT_JAN1) == 12
        assert periods_in_term("Quarterly", JAN1, NEXT_JAN1) == 4
        assert periods_in_term("Annual", JAN1, NEXT_JAN1) == 1

    def test_an_unknown_frequency_counts_the_amount_once(self):
        assert periods_in_term(None, JAN1, NEXT_JAN1) == 1


class TestCost:
    def test_a_monthly_premium_is_not_the_same_money_as_an_annual_one(self):
        # The defect this replaces summed both at face value.
        assert term_cost(D("150.00"), "Monthly", JAN1, NEXT_JAN1) == D("1800.00")
        assert term_cost(D("1800.00"), "Annual", JAN1, NEXT_JAN1) == D("1800.00")

    def test_only_the_part_inside_the_window_counts(self):
        half = cost_between(D("1200.00"), "Annual", JAN1, NEXT_JAN1, JAN1, JUL1)
        assert D("590") < half < D("600")

    def test_adjacent_terms_never_double_count_their_shared_boundary_day(self):
        first = cost_between(D("600.00"), "Semi-Annual", JAN1, JUL1, JAN1, NEXT_JAN1)
        second = cost_between(D("600.00"), "Semi-Annual", JUL1, NEXT_JAN1, JAN1, NEXT_JAN1)
        assert first + second == D("1200.00")

    def test_a_vehicle_that_left_mid_term_stops_costing(self):
        whole = cost_between(D("600.00"), "Semi-Annual", JAN1, JUL1, JAN1, JUL1)
        left = cost_between(
            D("600.00"), "Semi-Annual", JAN1, JUL1, JAN1, JUL1, effective_to=date(2026, 4, 1)
        )
        assert whole == D("600.00")
        assert D("295") < left < D("300")

    def test_an_upcoming_term_has_accrued_nothing(self):
        assert accrued_cost(D("700.00"), "Semi-Annual", JUL1, NEXT_JAN1, date(2026, 6, 1)) == 0

    def test_an_unknown_share_costs_nothing_rather_than_guessing(self):
        assert term_cost(None, "Annual", JAN1, NEXT_JAN1) == 0

    def test_monthly_costs_add_up_to_what_has_accrued(self):
        months = monthly_costs(D("600.00"), "Semi-Annual", JAN1, JUL1, JUL1)
        assert sorted(months) == [(2026, m) for m in range(1, 7)]
        assert abs(sum(months.values()) - D("600.00")) <= D("0.03")

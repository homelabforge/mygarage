"""What insurance cost over a span of days."""

from datetime import date, timedelta
from decimal import Decimal

from app.utils.insurance_cost import (
    accrued_cost,
    add_months,
    billing_periods,
    cost_between,
    monthly_costs,
    paid_cost,
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


class TestAddMonths:
    """Billing dates are calendar anniversaries, clamped to short months."""

    def test_the_same_day_of_the_month_later(self):
        assert add_months(date(2026, 1, 15), 1) == date(2026, 2, 15)
        assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)

    def test_a_month_end_start_clamps_to_the_last_day_of_a_short_month(self):
        assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
        assert add_months(date(2026, 8, 31), 1) == date(2026, 9, 30)

    def test_a_leap_year_february_has_a_29th(self):
        assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)
        assert add_months(date(2028, 1, 29), 1) == date(2028, 2, 29)
        assert add_months(date(2026, 1, 29), 1) == date(2026, 2, 28)

    def test_a_leap_day_start_lands_on_the_28th_in_other_years(self):
        assert add_months(date(2028, 2, 29), 12) == date(2029, 2, 28)
        assert add_months(date(2028, 2, 29), 48) == date(2032, 2, 29)

    def test_it_counts_from_the_original_date_so_the_day_comes_back(self):
        # Jan 31 -> Feb 28 -> Mar 31, not Feb 28 -> Mar 28.
        assert add_months(date(2026, 1, 31), 2) == date(2026, 3, 31)

    def test_a_december_start_rolls_into_the_next_year(self):
        assert add_months(date(2026, 12, 31), 2) == date(2027, 2, 28)
        assert add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)


class TestBillingPeriods:
    STARTS = [
        date(2026, 1, 1), date(2026, 1, 15), date(2026, 1, 29), date(2026, 1, 31),
        date(2026, 8, 31), date(2026, 12, 31), date(2028, 1, 31), date(2028, 2, 29),
    ]  # fmt: skip

    def test_periods_run_end_to_end_across_the_whole_term(self):
        for freq in ("Monthly", "Quarterly", "Semi-Annual", "Annual", None):
            for start in self.STARTS:
                end = add_months(start, 12)
                periods = billing_periods(freq, start, end)
                assert periods[0][0] == start, (freq, start)
                assert periods[-1][1] == end, (freq, start)
                for (_, prev_end), (next_start, _) in zip(periods, periods[1:], strict=False):
                    assert prev_end == next_start, (freq, start)
                for s, e in periods:
                    assert s < e, (freq, start)

    def test_the_count_matches_the_periods_the_term_cost_charges(self):
        for freq in ("Monthly", "Quarterly", "Semi-Annual", "Annual"):
            for start in self.STARTS:
                end = add_months(start, 12)
                assert len(billing_periods(freq, start, end)) == periods_in_term(freq, start, end)

    def test_a_year_of_monthly_billing_from_the_31st(self):
        starts = [s for s, _ in billing_periods("Monthly", date(2026, 1, 31), date(2027, 1, 31))]
        assert starts == [
            date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30),
            date(2026, 5, 31), date(2026, 6, 30), date(2026, 7, 31), date(2026, 8, 31),
            date(2026, 9, 30), date(2026, 10, 31), date(2026, 11, 30), date(2026, 12, 31),
        ]  # fmt: skip

    def test_quarterly_from_a_leap_day(self):
        starts = [s for s, _ in billing_periods("Quarterly", date(2028, 2, 29), date(2029, 2, 28))]
        assert starts == [
            date(2028, 2, 29),
            date(2028, 5, 29),
            date(2028, 8, 29),
            date(2028, 11, 29),
        ]


class TestPaidCost:
    """Each billing period counts in full once it has begun, never before."""

    def test_a_monthly_policy_counts_only_the_months_that_have_begun(self):
        # Jan 1, Feb 1 and Mar 1 have begun by Mar 12.
        assert paid_cost(D("10.00"), "Monthly", JAN1, NEXT_JAN1, date(2026, 3, 12)) == D("30.00")

    def test_a_period_counts_on_its_anniversary_and_not_the_day_before(self):
        assert paid_cost(D("10.00"), "Monthly", JAN1, NEXT_JAN1, date(2026, 1, 31)) == D("10.00")
        assert paid_cost(D("10.00"), "Monthly", JAN1, NEXT_JAN1, date(2026, 2, 1)) == D("20.00")
        assert paid_cost(D("10.00"), "Monthly", JAN1, NEXT_JAN1, date(2026, 2, 28)) == D("20.00")
        assert paid_cost(D("10.00"), "Monthly", JAN1, NEXT_JAN1, date(2026, 3, 1)) == D("30.00")

    def test_a_mid_month_policy_bills_on_the_same_day_each_month(self):
        start, end = date(2026, 1, 15), date(2027, 1, 15)
        assert paid_cost(D("10.00"), "Monthly", start, end, date(2026, 3, 14)) == D("20.00")
        assert paid_cost(D("10.00"), "Monthly", start, end, date(2026, 3, 15)) == D("30.00")

    def test_february_in_an_ordinary_year(self):
        start, end = date(2026, 1, 31), date(2027, 1, 31)
        assert paid_cost(D("10.00"), "Monthly", start, end, date(2026, 2, 27)) == D("10.00")
        assert paid_cost(D("10.00"), "Monthly", start, end, date(2026, 2, 28)) == D("20.00")
        assert paid_cost(D("10.00"), "Monthly", start, end, date(2026, 3, 30)) == D("20.00")
        assert paid_cost(D("10.00"), "Monthly", start, end, date(2026, 3, 31)) == D("30.00")

    def test_february_in_a_leap_year(self):
        start, end = date(2028, 1, 31), date(2029, 1, 31)
        assert paid_cost(D("10.00"), "Monthly", start, end, date(2028, 2, 28)) == D("10.00")
        assert paid_cost(D("10.00"), "Monthly", start, end, date(2028, 2, 29)) == D("20.00")

    def test_a_policy_starting_on_a_month_end(self):
        start, end = date(2026, 8, 31), date(2027, 8, 31)
        assert paid_cost(D("10.00"), "Monthly", start, end, date(2026, 9, 29)) == D("10.00")
        assert paid_cost(D("10.00"), "Monthly", start, end, date(2026, 9, 30)) == D("20.00")
        assert paid_cost(D("10.00"), "Monthly", start, end, date(2026, 10, 31)) == D("30.00")

    def test_a_policy_starting_on_a_leap_day(self):
        start, end = date(2028, 2, 29), date(2029, 2, 28)
        assert paid_cost(D("25.00"), "Quarterly", start, end, date(2028, 5, 28)) == D("25.00")
        assert paid_cost(D("25.00"), "Quarterly", start, end, date(2028, 5, 29)) == D("50.00")

    def test_the_first_period_counts_on_the_start_date(self):
        assert paid_cost(D("10.00"), "Monthly", JAN1, NEXT_JAN1, JAN1) == D("10.00")

    def test_a_finished_term_counts_every_period_and_matches_the_term_cost(self):
        assert paid_cost(D("10.00"), "Monthly", JAN1, NEXT_JAN1, date(2027, 6, 1)) == D("120.00")
        for freq in ("Monthly", "Quarterly", "Semi-Annual", "Annual"):
            for start in TestBillingPeriods.STARTS:
                end = add_months(start, 12)
                assert paid_cost(D("7.00"), freq, start, end, end) == term_cost(
                    D("7.00"), freq, start, end
                ), (freq, start)

    def test_a_single_period_term_counts_whole_from_its_start(self):
        assert paid_cost(D("180.00"), "Semi-Annual", JAN1, JUL1, date(2026, 1, 2)) == D("180.00")
        assert paid_cost(D("900.00"), "Annual", JAN1, NEXT_JAN1, date(2026, 1, 2)) == D("900.00")

    def test_a_future_term_counts_nothing(self):
        assert paid_cost(D("10.00"), "Monthly", JUL1, NEXT_JAN1, date(2026, 6, 30)) == D("0.00")
        assert paid_cost(D("180.00"), "Semi-Annual", JUL1, NEXT_JAN1, date(2026, 6, 30)) == D(
            "0.00"
        )

    def test_it_stays_within_one_payment_of_the_accrual_every_day_of_the_term(self):
        # The two bases place the same money differently (whole at the start of
        # each period vs evenly by day), so they differ by up to one payment, a
        # little over right after a billing date because calendar months are not
        # all 30.4 days long (measured worst case: 1.05 payments). They must
        # never drift further apart than that.
        share = D("10.00")
        for start in TestBillingPeriods.STARTS:
            end = add_months(start, 12)
            for offset in range((end - start).days + 1):
                today = start + timedelta(days=offset)
                paid = paid_cost(share, "Monthly", start, end, today)
                accrued = accrued_cost(share, "Monthly", start, end, today)
                assert abs(paid - accrued) <= share * D("1.1"), (start, today, paid, accrued)

    def test_a_vehicle_that_left_early_is_prorated_by_the_periods_own_days(self):
        # Cover ends Feb 15: January in full, half of February (14 of 28 days),
        # and March never began for this vehicle.
        got = paid_cost(
            D("10.00"),
            "Monthly",
            JAN1,
            NEXT_JAN1,
            date(2026, 3, 12),
            effective_to=date(2026, 2, 15),
        )
        assert got == D("15.00")

    def test_leaving_on_a_billing_date_costs_nothing_for_that_period(self):
        got = paid_cost(
            D("10.00"), "Monthly", JAN1, NEXT_JAN1, date(2026, 3, 12), effective_to=date(2026, 2, 1)
        )
        assert got == D("10.00")

    def test_cover_that_runs_past_the_periods_counted_is_not_prorated(self):
        got = paid_cost(
            D("10.00"), "Monthly", JAN1, NEXT_JAN1, date(2026, 3, 12), effective_to=date(2026, 9, 1)
        )
        assert got == D("30.00")

    def test_a_single_period_term_that_ended_early_is_prorated_over_the_term(self):
        got = paid_cost(
            D("180.00"), "Semi-Annual", JAN1, JUL1, date(2026, 5, 1), effective_to=date(2026, 4, 1)
        )
        assert got == D("89.50")  # cover ran 90 of the term's 181 days

    def test_a_term_with_no_days_is_one_period_counted_whole(self):
        day = date(2026, 3, 1)
        assert billing_periods("Monthly", day, day) == [(day, day)]
        assert paid_cost(D("10.00"), "Monthly", day, day, date(2026, 3, 1)) == D("10.00")
        assert paid_cost(D("10.00"), "Monthly", day, day, date(2026, 2, 28)) == D("0.00")

    def test_a_term_with_no_days_follows_the_vehicles_cover(self):
        day = date(2026, 3, 1)
        reached = paid_cost(D("10.00"), "Monthly", day, day, date(2026, 6, 1), effective_to=day)
        before = paid_cost(
            D("10.00"), "Monthly", day, day, date(2026, 6, 1), effective_to=date(2026, 2, 1)
        )
        assert reached == D("10.00")
        assert before == D("0.00")

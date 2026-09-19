"""How a policy's premium divides among its vehicles."""

from decimal import Decimal

import pytest

from app.utils.insurance_shares import (
    AllocationError,
    effective_shares,
    rescale_shares,
    validate_allocation,
)

D = Decimal


class TestEffectiveShares:
    def test_unset_shares_split_the_total_evenly(self):
        assert effective_shares(D("600.00"), [(1, None), (2, None)]) == {
            1: D("300.00"),
            2: D("300.00"),
        }

    def test_unset_shares_split_what_the_explicit_ones_leave(self):
        got = effective_shares(D("600.00"), [(1, D("400.00")), (2, None), (3, None)])
        assert got == {1: D("400.00"), 2: D("100.00"), 3: D("100.00")}

    def test_the_leftover_cents_go_to_the_earliest_links_and_the_sum_is_exact(self):
        got = effective_shares(D("100.00"), [(1, None), (2, None), (3, None)])
        assert got == {1: D("33.34"), 2: D("33.33"), 3: D("33.33")}
        assert sum(got.values()) == D("100.00")

    def test_two_leftover_cents_are_spread_not_stacked(self):
        got = effective_shares(D("100.01"), [(1, None), (2, None), (3, None)])
        assert got == {1: D("33.34"), 2: D("33.34"), 3: D("33.33")}

    def test_an_unknown_total_leaves_unset_shares_unknown(self):
        assert effective_shares(None, [(1, D("50.00")), (2, None)]) == {1: D("50.00"), 2: None}


class TestValidateAllocation:
    def test_fully_explicit_shares_must_sum_to_the_total_exactly(self):
        validate_allocation(D("600.00"), [D("300.00"), D("300.00")])
        with pytest.raises(AllocationError):
            validate_allocation(D("700.00"), [D("300.00"), D("300.00")])

    def test_partly_explicit_shares_may_not_exceed_the_total(self):
        validate_allocation(D("600.00"), [D("500.00"), None])
        with pytest.raises(AllocationError):
            validate_allocation(D("600.00"), [D("700.00"), None])

    def test_an_unknown_total_cannot_be_contradicted(self):
        validate_allocation(None, [D("300.00"), D("300.00")])

    def test_a_policy_with_no_vehicles_is_valid(self):
        validate_allocation(D("600.00"), [])


class TestRescaleShares:
    def test_a_renewal_allocates_the_whole_new_premium(self):
        got = rescale_shares([(1, D("300.00")), (2, D("300.00"))], D("600.00"), D("700.00"))
        assert got == {1: D("350.00"), 2: D("350.00")}
        validate_allocation(D("700.00"), list(got.values()))

    def test_rounding_never_loses_a_cent(self):
        got = rescale_shares(
            [(1, D("100.00")), (2, D("100.00")), (3, D("100.00"))], D("300.00"), D("100.00")
        )
        assert sum(v for v in got.values() if v is not None) == D("100.00")

    def test_unset_shares_stay_unset(self):
        got = rescale_shares([(1, D("400.00")), (2, None)], D("600.00"), D("900.00"))
        assert got == {1: D("600.00"), 2: None}

    @pytest.mark.parametrize("old", [None, D("0")])
    def test_no_usable_old_total_resets_to_an_even_split(self, old):
        assert rescale_shares([(1, D("5.00")), (2, None)], old, D("700.00")) == {1: None, 2: None}

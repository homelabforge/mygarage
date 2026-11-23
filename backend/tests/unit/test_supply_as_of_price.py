"""A usage's price as of its visit's date (#307), and its parity with migration 163.

163 prices stranded rows at upgrade and the app prices everything after, so the
two rules must agree to the last rounding. The scenario numbers are 163's: a
July 2025 purchase of 5 for $30.00, a June 2026 one of 5 for $37.45, and a
visit on 2025-07-17.
"""

import itertools
from datetime import date
from decimal import Decimal

import pytest

from app.services.supply_service import CostedPurchase, as_of_price
from tests.migrations._loader import load_migration

JULY_2025: CostedPurchase = (date(2025, 7, 10), Decimal("5"), Decimal("30.00"))
JUNE_2026: CostedPurchase = (date(2026, 6, 2), Decimal("5"), Decimal("37.45"))
VISIT_DAY = date(2025, 7, 17)


def test_both_purchases_price_at_july() -> None:
    assert as_of_price([JULY_2025, JUNE_2026], VISIT_DAY) == (Decimal("6.0000"), False)


def test_only_june_falls_back_and_flags() -> None:
    assert as_of_price([JUNE_2026], VISIT_DAY) == (Decimal("7.4900"), True)


def test_a_purchase_on_the_day_counts() -> None:
    assert as_of_price([JUNE_2026], JUNE_2026[0]) == (Decimal("7.4900"), False)


def test_nothing_costed_is_none() -> None:
    assert as_of_price([], VISIT_DAY) is None


def test_the_average_rounds_half_up_at_four_places() -> None:
    # 67.45 over 10 = 6.745 exactly; 0.00005 over 1 rounds up.
    assert as_of_price([JULY_2025, JUNE_2026], date(2026, 7, 1)) == (Decimal("6.7450"), False)
    tiny: CostedPurchase = (date(2025, 1, 1), Decimal("2"), Decimal("0.01"))
    assert as_of_price([tiny], VISIT_DAY) == (Decimal("0.0050"), False)
    third: CostedPurchase = (date(2025, 1, 1), Decimal("3"), Decimal("1.00"))
    assert as_of_price([third], VISIT_DAY) == (Decimal("0.3333"), False)


_PURCHASES: list[CostedPurchase] = [
    JULY_2025,
    JUNE_2026,
    (date(2025, 7, 17), Decimal("3"), Decimal("1.00")),
    (date(2024, 1, 1), Decimal("0.5"), Decimal("0")),
    (date(2026, 9, 1), Decimal("4.73176473"), Decimal("50.00")),
]
_DAYS = [date(2024, 1, 1), date(2025, 7, 16), VISIT_DAY, date(2026, 6, 2), date(2027, 1, 1)]


@pytest.mark.parametrize(
    "subset",
    [list(c) for n in range(len(_PURCHASES) + 1) for c in itertools.combinations(_PURCHASES, n)],
)
def test_matches_migration_163(subset: list[CostedPurchase]) -> None:
    migration = load_migration("163_price_visit_usages_as_of")
    for day in _DAYS:
        assert as_of_price(subset, day) == migration._as_of(subset, day), day

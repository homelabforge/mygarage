"""The pricing rule for a usage logged before its supply had a cost (#301)."""

from decimal import Decimal

import pytest

from app.models.supply import SupplyUsage
from app.schemas._money import MONEY_MAX, UNIT_COST_MAX
from app.services.supply_service import price_unpriced_usage, usage_price


def _usage(unit: str | None, cost: str | None, quantity: str = "3") -> SupplyUsage:
    return SupplyUsage(
        supply_id=1,
        quantity=Decimal(quantity),
        unit_cost_snapshot=None if unit is None else Decimal(unit),
        cost_snapshot=None if cost is None else Decimal(cost),
    )


@pytest.mark.parametrize("unit", ["4.0000", None], ids=["both set", "cost only (an import)"])
def test_a_priced_usage_is_never_repriced(unit: str | None) -> None:
    usage = _usage(unit, "12.00")
    assert price_unpriced_usage(usage, Decimal("9")) is False
    assert usage.cost_snapshot == Decimal("12.00")
    assert usage.unit_cost_snapshot == (None if unit is None else Decimal(unit))


def test_unpriced_takes_the_average() -> None:
    usage = _usage(None, None)
    assert price_unpriced_usage(usage, Decimal("7.9146")) is True
    assert usage.unit_cost_snapshot == Decimal("7.9146")
    assert usage.cost_snapshot == Decimal("23.74")  # 23.7438 half-up


def test_a_frozen_unit_beats_the_average() -> None:
    usage = _usage("5.0000", None, quantity="2")
    assert price_unpriced_usage(usage, Decimal("9")) is True
    assert usage.unit_cost_snapshot == Decimal("5.0000")
    assert usage.cost_snapshot == Decimal("10.00")


def test_nothing_to_price_with() -> None:
    usage = _usage(None, None)
    assert price_unpriced_usage(usage, None) is False
    assert usage.cost_snapshot is None


def test_half_cent_rounds_up() -> None:
    assert usage_price(None, Decimal("1"), Decimal("1.0050")) == (
        Decimal("1.0050"),
        Decimal("1.01"),
    )


def test_what_wont_fit_stays_unpriced() -> None:
    assert usage_price(None, Decimal("1"), UNIT_COST_MAX + Decimal("0.0001")) is None
    assert usage_price(None, Decimal("2"), MONEY_MAX) is None
    assert usage_price(None, Decimal("1"), MONEY_MAX) == (MONEY_MAX, MONEY_MAX)

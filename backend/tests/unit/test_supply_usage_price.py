"""The pricing rule for a usage logged before its supply had a cost (#301),
and for an estimate settling once its visit has a price of its own (#307)."""

from decimal import Decimal

import pytest

from app.models.supply import SupplyUsage
from app.schemas._money import MONEY_MAX, UNIT_COST_MAX
from app.services.supply_service import AsOfPrice, price_unsettled_usage, usage_price


def _usage(
    unit: str | None, cost: str | None, quantity: str = "3", estimated: bool = False
) -> SupplyUsage:
    return SupplyUsage(
        supply_id=1,
        quantity=Decimal(quantity),
        unit_cost_snapshot=None if unit is None else Decimal(unit),
        cost_snapshot=None if cost is None else Decimal(cost),
        cost_estimated=estimated,
    )


def _real(unit: str) -> AsOfPrice:
    """A price as of the visit, from a purchase on or before it."""
    return Decimal(unit), False


def _fallback(unit: str) -> AsOfPrice:
    """The all-time average, with nothing on or before the visit."""
    return Decimal(unit), True


@pytest.mark.parametrize("unit", ["4.0000", None], ids=["both set", "cost only (an import)"])
def test_a_priced_usage_is_never_repriced(unit: str | None) -> None:
    usage = _usage(unit, "12.00")
    assert price_unsettled_usage(usage, _real("9")) is False
    assert usage.cost_snapshot == Decimal("12.00")
    assert usage.unit_cost_snapshot == (None if unit is None else Decimal(unit))


def test_unpriced_takes_the_average() -> None:
    usage = _usage(None, None)
    assert price_unsettled_usage(usage, _real("7.9146")) is True
    assert usage.unit_cost_snapshot == Decimal("7.9146")
    assert usage.cost_snapshot == Decimal("23.74")  # 23.7438 half-up


def test_a_frozen_unit_beats_the_average() -> None:
    usage = _usage("5.0000", None, quantity="2")
    assert price_unsettled_usage(usage, _real("9")) is True
    assert usage.unit_cost_snapshot == Decimal("5.0000")
    assert usage.cost_snapshot == Decimal("10.00")


def test_nothing_to_price_with() -> None:
    usage = _usage(None, None)
    assert price_unsettled_usage(usage, None) is False
    assert usage.cost_snapshot is None


def test_unpriced_takes_the_fallback_flagged() -> None:
    usage = _usage(None, None, quantity="5")
    assert price_unsettled_usage(usage, _fallback("7.4900")) is True
    assert (usage.unit_cost_snapshot, usage.cost_snapshot) == (Decimal("7.4900"), Decimal("37.45"))
    assert usage.cost_estimated is True


def test_a_frozen_unit_beats_the_fallback_and_is_not_an_estimate() -> None:
    usage = _usage("5.0000", None, quantity="2")
    assert price_unsettled_usage(usage, _fallback("9")) is True
    assert (usage.cost_snapshot, usage.cost_estimated) == (Decimal("10.00"), False)


def test_an_unpriced_flagged_row_ignores_its_own_unit() -> None:
    usage = _usage("5.0000", None, quantity="2", estimated=True)
    assert price_unsettled_usage(usage, _real("6.0000")) is True
    assert (usage.unit_cost_snapshot, usage.cost_snapshot) == (Decimal("6.0000"), Decimal("12.00"))
    assert usage.cost_estimated is False


def test_an_estimate_settles_on_a_real_price() -> None:
    usage = _usage("7.4900", "37.45", quantity="5", estimated=True)
    assert price_unsettled_usage(usage, _real("6.0000")) is True
    assert (usage.unit_cost_snapshot, usage.cost_snapshot) == (Decimal("6.0000"), Decimal("30.00"))
    assert usage.cost_estimated is False


def test_an_estimate_settling_at_the_same_amount_clears_the_flag() -> None:
    usage = _usage("6.0000", "30.00", quantity="5", estimated=True)
    assert price_unsettled_usage(usage, _real("6.0000")) is True
    assert (usage.cost_snapshot, usage.cost_estimated) == (Decimal("30.00"), False)


@pytest.mark.parametrize("found", [_fallback("9.0000"), None], ids=["fallback", "nothing"])
def test_an_estimate_moves_on_nothing_but_a_real_price(found: AsOfPrice | None) -> None:
    usage = _usage("7.4900", "37.45", quantity="5", estimated=True)
    assert price_unsettled_usage(usage, found) is False
    assert (usage.unit_cost_snapshot, usage.cost_snapshot) == (Decimal("7.4900"), Decimal("37.45"))
    assert usage.cost_estimated is True


def test_half_cent_rounds_up() -> None:
    assert usage_price(None, Decimal("1"), Decimal("1.0050")) == (
        Decimal("1.0050"),
        Decimal("1.01"),
    )


def test_what_wont_fit_stays_unpriced() -> None:
    assert usage_price(None, Decimal("1"), UNIT_COST_MAX + Decimal("0.0001")) is None
    assert usage_price(None, Decimal("2"), MONEY_MAX) is None
    assert usage_price(None, Decimal("1"), MONEY_MAX) == (MONEY_MAX, MONEY_MAX)

"""Computed L/100km comes at four places, the scale the consumption columns hold.

It rounded to two, the old NUMERIC(5,2) grain, so an imperial reader's MPG
was converted from a figure already 0.005 L/100km off.
"""

from datetime import date
from decimal import Decimal

from app.models.fuel import FuelRecord
from app.services.analytics_service import calculate_fuel_economy_with_pandas
from app.services.fuel_service import (
    average_l_per_100km,
    calculate_l_per_100km,
    economy_periods,
)


def _fill(odometer_km: str, liters: str, day: int, record_id: int) -> FuelRecord:
    return FuelRecord(
        id=record_id,
        vin="1HGCM82633A004352",
        date=date(2026, 9, day),
        odometer_km=Decimal(odometer_km),
        liters=Decimal(liters),
        is_full_tank=True,
        missed_fillup=False,
        is_hauling=False,
    )


# 40 L over 573 km = 6.98080279...; 42 L over 600 km = 7.0 exactly.
FILLS = [
    _fill("10000.00", "40.000", 1, 1),
    _fill("10573.00", "40.000", 8, 2),
    _fill("11173.00", "42.000", 15, 3),
]


def test_a_tank_figure_keeps_four_places() -> None:
    assert calculate_l_per_100km(FILLS[1], FILLS[0], Decimal("40.000")) == Decimal("6.9808")


def test_the_average_keeps_four_places() -> None:
    # 82 L over 1173 km = 6.99062233...
    assert average_l_per_100km(economy_periods(FILLS)) == Decimal("6.9906")


def test_analytics_best_worst_and_recent_keep_four_places() -> None:
    frame, stats = calculate_fuel_economy_with_pandas(FILLS)
    assert stats["best_l_per_100km"] == Decimal("6.9808")
    assert stats["worst_l_per_100km"] == Decimal("7.0000")
    assert stats["recent_l_per_100km"] == Decimal("7.0000")
    assert list(frame["l_per_100km"]) == [6.9808, 7.0]


async def test_the_analytics_trend_points_keep_four_places() -> None:
    from types import SimpleNamespace

    from app.routes.analytics import get_fuel_economy_trend

    class _Db:
        async def execute(self, _stmt: object) -> SimpleNamespace:
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: FILLS))

    # Past the cache, so another test's trend can't answer for this one.
    trend = await get_fuel_economy_trend.__wrapped__(_Db(), FILLS[0].vin)
    assert [p.l_per_100km for p in trend.data_points] == [Decimal("6.9808"), Decimal("7.0000")]
    assert trend.best_l_per_100km == Decimal("6.9808")

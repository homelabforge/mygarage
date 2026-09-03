"""Unit tests for the engine-hours fuel economy (gal/hr + cost/hr).

The hours analog of L/100km, over each full-tank interval's Δengine_hours:
``l_per_hr = Σ liters / Δhours`` and ``cost_per_hr = Σ net-cost / Δhours``.

The crux (design-review finding R1-H5): BOTH numerators must accumulate every
PARTIAL fill since the previous full-tank endpoint — not just the endpoint's
own fill. These tests hand-compute known figures so an endpoint-only
regression is caught for liters AND cost. Endpoint/missed/hauling rules must
stay identical to the distance calc so the two dimensions never drift.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fuel import FuelRecord
from app.models.vehicle import Vehicle
from app.services.fuel_service import (
    calculate_average_hours_economy,
    calculate_hours_economy,
    compute_full_tank_hours_economy,
)


def _fr(
    hours: str | None,
    liters: str | None,
    cost: str | None,
    *,
    full: bool = True,
    hauling: bool = False,
    missed: bool = False,
) -> FuelRecord:
    """Terse FuelRecord factory for the hours-economy unit tests."""
    return FuelRecord(
        vin="HOURSECON00000000",
        date=date(2026, 1, 1),
        engine_hours=Decimal(hours) if hours is not None else None,
        liters=Decimal(liters) if liters is not None else None,
        cost=Decimal(cost) if cost is not None else None,
        is_full_tank=full,
        is_hauling=hauling,
        missed_fillup=missed,
    )


@pytest.mark.unit
@pytest.mark.fuel
class TestComputeFullTankHoursEconomy:
    """The single source of truth for per-record + average hours economy."""

    def test_folds_partial_liters_and_cost_into_both_figures(self) -> None:
        """CRUX: a partial fill's liters AND cost fold into the next full tank.

        Interval prev(100h) -> partial(110h) -> cur(120h), Δ = 20h.
        Numerators are the partial + the endpoint (NOT the endpoint alone):
            l_per_hr    = (10.000 + 15.000) / 20 = 1.25
            cost_per_hr = (18.00  + 25.00 ) / 20 = 2.15
        Endpoint-only (the R1-H5 bug) would give 0.75 and 1.25 — proven wrong.
        """
        prev = _fr("100.0", "20.000", "30.00")
        partial = _fr("110.0", "10.000", "18.00", full=False)
        cur = _fr("120.0", "15.000", "25.00")

        results = compute_full_tank_hours_economy([prev, partial, cur])

        assert len(results) == 1, "only the second full tank has a predecessor"
        rec, l_per_hr, cost_per_hr = results[0]
        assert rec.engine_hours == Decimal("120.0")
        assert l_per_hr == Decimal("1.25")
        assert cost_per_hr == Decimal("2.15")
        # Explicitly reject the endpoint-only numerators.
        assert l_per_hr != Decimal("0.75")
        assert cost_per_hr != Decimal("1.25")

    def test_folds_multiple_partials(self) -> None:
        """Two partials in one interval both fold into liters and cost."""
        prev = _fr("200.0", "30.000", "40.00")
        p1 = _fr("210.0", "5.000", "8.00", full=False)
        p2 = _fr("225.0", "7.000", "12.00", full=False)
        cur = _fr("250.0", "18.000", "30.00")

        results = compute_full_tank_hours_economy([prev, p1, p2, cur])

        # Δ = 250 - 200 = 50; liters = 5+7+18 = 30; cost = 8+12+30 = 50.
        assert len(results) == 1
        _, l_per_hr, cost_per_hr = results[0]
        assert l_per_hr == Decimal("0.60")  # 30 / 50
        assert cost_per_hr == Decimal("1.00")  # 50 / 50

    def test_single_full_tank_yields_no_figure(self) -> None:
        """No predecessor endpoint -> no figure (mirror distance)."""
        assert compute_full_tank_hours_economy([_fr("100.0", "20.000", "30.00")]) == []

    def test_missed_fillup_is_endpoint_but_no_figure_and_reanchors(self) -> None:
        """A missed full tank yields no figure and re-anchors the next interval.

        prev(100h) -> missed(110h) -> cur(130h). The missed record's own fuel
        is discarded on re-anchor, so cur's numerator is ITS fuel only over
        Δ = 130 - 110 = 20h: l = 15/20 = 0.75, cost = 25/20 = 1.25.
        """
        prev = _fr("100.0", "20.000", "30.00")
        missed = _fr("110.0", "10.000", "18.00", missed=True)
        cur = _fr("130.0", "15.000", "25.00")

        results = compute_full_tank_hours_economy([prev, missed, cur])

        assert len(results) == 1
        rec, l_per_hr, cost_per_hr = results[0]
        assert rec.engine_hours == Decimal("130.0")
        assert l_per_hr == Decimal("0.75")
        assert cost_per_hr == Decimal("1.25")

    def test_hauling_folds_into_interval_when_excluded(self) -> None:
        """exclude_hauling: a hauling full tank is not an endpoint; its fuel
        folds into the surrounding interval instead of splitting it."""
        a = _fr("100.0", "40.000", "60.00")
        hauling = _fr("150.0", "30.000", "45.00", hauling=True)
        b = _fr("200.0", "45.000", "70.00")

        excluded = compute_full_tank_hours_economy([a, hauling, b], exclude_hauling=True)
        # a -> b bridge: Δ = 100h; liters = 30+45 = 75; cost = 45+70 = 115.
        assert len(excluded) == 1
        _, l_per_hr, cost_per_hr = excluded[0]
        assert l_per_hr == Decimal("0.75")  # 75 / 100
        assert cost_per_hr == Decimal("1.15")  # 115 / 100

        # Without exclusion the hauling tank splits the interval into two.
        included = compute_full_tank_hours_economy([a, hauling, b], exclude_hauling=False)
        assert len(included) == 2

    def test_non_increasing_hours_yields_no_figure(self) -> None:
        """Δhours <= 0 (meter did not advance) -> no figure."""
        prev = _fr("100.0", "20.000", "30.00")
        same = _fr("100.0", "15.000", "25.00")
        assert compute_full_tank_hours_economy([prev, same]) == []

    def test_skips_records_without_engine_hours(self) -> None:
        """A fill with no engine_hours is off the hours axis: it does not fold.

        prev(100h) -> partial(no hours) -> cur(120h). The hours-less partial is
        skipped entirely, so cur's numerator excludes it: l = 15/20 = 0.75.
        """
        prev = _fr("100.0", "20.000", "30.00")
        no_hours = _fr(None, "10.000", "18.00", full=False)
        cur = _fr("120.0", "15.000", "25.00")

        results = compute_full_tank_hours_economy([prev, no_hours, cur])

        assert len(results) == 1
        _, l_per_hr, cost_per_hr = results[0]
        assert l_per_hr == Decimal("0.75")
        assert cost_per_hr == Decimal("1.25")

    def test_zero_liters_interval_yields_none_l_per_hr_but_keeps_cost_per_hr(self) -> None:
        """P3 backlog fix: a zero-liters full-tank interval must not compute
        l_per_hr as 0.00 (which would drag average_l_per_hr toward zero) — it
        yields NO l_per_hr figure at all. cost_per_hr is still valid over the
        same Δhours (e.g. a $0-fuel top-off logged purely for the hours
        reading, or a paid stop where the cost was billed separately).

        prev(100h, $30) -> cur(120h, 0.000L, $15.00): Δ = 20h.
        l_per_hr = None (interval_liters == 0); cost_per_hr = 15/20 = 0.75.
        """
        prev = _fr("100.0", "20.000", "30.00")
        cur = _fr("120.0", "0.000", "15.00")

        results = compute_full_tank_hours_economy([prev, cur])

        assert len(results) == 1, "the record itself is still a scored endpoint"
        rec, l_per_hr, cost_per_hr = results[0]
        assert rec.engine_hours == Decimal("120.0")
        assert l_per_hr is None
        assert cost_per_hr == Decimal("0.75")


@pytest.mark.unit
@pytest.mark.fuel
class TestCalculateHoursEconomy:
    """The single-endpoint helper mirrors calculate_l_per_100km's guards."""

    def test_valid_pair(self) -> None:
        prev = _fr("100.0", "20.000", "30.00")
        cur = _fr("120.0", "15.000", "25.00")
        figure = calculate_hours_economy(cur, prev, Decimal("15.000"), Decimal("25.00"))
        assert figure == (Decimal("0.75"), Decimal("1.25"))

    def test_partial_returns_none(self) -> None:
        prev = _fr("100.0", "20.000", "30.00")
        cur = _fr("120.0", "15.000", "25.00", full=False)
        assert calculate_hours_economy(cur, prev, Decimal("15.000"), Decimal("25.00")) is None

    def test_missed_returns_none(self) -> None:
        prev = _fr("100.0", "20.000", "30.00")
        cur = _fr("120.0", "15.000", "25.00", missed=True)
        assert calculate_hours_economy(cur, prev, Decimal("15.000"), Decimal("25.00")) is None

    def test_no_previous_returns_none(self) -> None:
        cur = _fr("120.0", "15.000", "25.00")
        assert calculate_hours_economy(cur, None, Decimal("15.000"), Decimal("25.00")) is None

    def test_zero_delta_returns_none(self) -> None:
        prev = _fr("120.0", "20.000", "30.00")
        cur = _fr("120.0", "15.000", "25.00")
        assert calculate_hours_economy(cur, prev, Decimal("15.000"), Decimal("25.00")) is None

    def test_negative_delta_returns_none(self) -> None:
        prev = _fr("130.0", "20.000", "30.00")
        cur = _fr("120.0", "15.000", "25.00")
        assert calculate_hours_economy(cur, prev, Decimal("15.000"), Decimal("25.00")) is None

    def test_missing_current_hours_returns_none(self) -> None:
        prev = _fr("100.0", "20.000", "30.00")
        cur = _fr(None, "15.000", "25.00")
        assert calculate_hours_economy(cur, prev, Decimal("15.000"), Decimal("25.00")) is None

    def test_rounds_to_two_places(self) -> None:
        prev = _fr("100.0", "20.000", "30.00")
        cur = _fr("103.0", "10.000", "10.00")
        # Δ = 3h; l = 10/3 = 3.333... -> 3.33; cost = 10/3 = 3.333... -> 3.33.
        figure = calculate_hours_economy(cur, prev, Decimal("10.000"), Decimal("10.00"))
        assert figure is not None
        l_per_hr, cost_per_hr = figure
        assert l_per_hr == Decimal("3.33")
        assert cost_per_hr == Decimal("3.33")
        assert l_per_hr is not None
        assert l_per_hr.as_tuple().exponent == -2

    def test_zero_liters_returns_none_l_per_hr_but_keeps_cost_per_hr(self) -> None:
        """P3 backlog fix: interval_liters <= 0 -> l_per_hr is None (no figure
        at all, never 0.00), but cost_per_hr is still computed over the same
        Δhours — cost/hr is valid with zero liquid fuel."""
        prev = _fr("100.0", "20.000", "30.00")
        cur = _fr("120.0", "0.000", "40.00")
        figure = calculate_hours_economy(cur, prev, Decimal("0.000"), Decimal("40.00"))
        assert figure is not None
        l_per_hr, cost_per_hr = figure
        assert l_per_hr is None
        assert cost_per_hr == Decimal("2.00")  # 40 / 20


@pytest.mark.unit
@pytest.mark.fuel
@pytest.mark.asyncio
class TestCalculateAverageHoursEconomySkipsZeroLiters:
    """P3 backlog fix at the vehicle-average level (db-backed)."""

    async def test_zero_liters_interval_excluded_from_l_per_hr_average_not_cost(
        self, db_session: AsyncSession
    ) -> None:
        """Two intervals: a normal one (l/hr=1.00, cost/hr=1.50) and a
        zero-liters one (l/hr=None, cost/hr=2.00). average_l_per_hr must be
        the normal interval ALONE (1.00), not dragged toward 0 by averaging
        in a phantom 0.00; average_cost_per_hr averages BOTH intervals
        (1.75), since cost/hr is never suppressed for want of liters.
        """
        vin = "HOURSAVGZERO00001"
        db_session.add(Vehicle(vin=vin, nickname="Avg Zero Liters", vehicle_type="Car"))
        await db_session.flush()
        db_session.add_all(
            [
                FuelRecord(
                    vin=vin,
                    date=date(2026, 1, 1),
                    engine_hours=Decimal("100.0"),
                    liters=Decimal("20.000"),
                    cost=Decimal("30.00"),
                    is_full_tank=True,
                ),
                # Interval 1 (100h -> 120h, Δ=20h): l/hr = 20/20 = 1.00, cost/hr = 30/20 = 1.50.
                FuelRecord(
                    vin=vin,
                    date=date(2026, 1, 5),
                    engine_hours=Decimal("120.0"),
                    liters=Decimal("20.000"),
                    cost=Decimal("30.00"),
                    is_full_tank=True,
                ),
                # Interval 2 (120h -> 140h, Δ=20h): 0 liters -> l/hr None; cost/hr = 40/20 = 2.00.
                FuelRecord(
                    vin=vin,
                    date=date(2026, 1, 10),
                    engine_hours=Decimal("140.0"),
                    liters=Decimal("0.000"),
                    cost=Decimal("40.00"),
                    is_full_tank=True,
                ),
            ]
        )
        await db_session.commit()

        avg_l_per_hr, avg_cost_per_hr = await calculate_average_hours_economy(db_session, vin)

        assert avg_l_per_hr == Decimal("1.00")
        assert avg_cost_per_hr == Decimal("1.75")  # mean(1.50, 2.00)

    async def test_all_zero_liters_yields_none_average_l_per_hr_but_averages_cost(
        self, db_session: AsyncSession
    ) -> None:
        """When EVERY scored interval is zero-liters, average_l_per_hr must be
        None (never a ZeroDivisionError, never a phantom 0.00) while
        average_cost_per_hr still averages the valid cost/hr figures."""
        vin = "HOURSAVGZERO00002"
        db_session.add(Vehicle(vin=vin, nickname="Avg All Zero", vehicle_type="Car"))
        await db_session.flush()
        db_session.add_all(
            [
                FuelRecord(
                    vin=vin,
                    date=date(2026, 2, 1),
                    engine_hours=Decimal("50.0"),
                    liters=Decimal("15.000"),
                    cost=Decimal("20.00"),
                    is_full_tank=True,
                ),
                # 50h -> 70h, Δ=20h, 0 liters -> l/hr None; cost/hr = 20/20 = 1.00.
                FuelRecord(
                    vin=vin,
                    date=date(2026, 2, 5),
                    engine_hours=Decimal("70.0"),
                    liters=Decimal("0.000"),
                    cost=Decimal("20.00"),
                    is_full_tank=True,
                ),
            ]
        )
        await db_session.commit()

        avg_l_per_hr, avg_cost_per_hr = await calculate_average_hours_economy(db_session, vin)

        assert avg_l_per_hr is None
        assert avg_cost_per_hr == Decimal("1.00")

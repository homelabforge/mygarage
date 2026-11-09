"""Derived-quantity formatting: fuel rate and cost per distance -- the two
functions `unit_derived.py` builds on top of `unit_formatting.py`'s
simple-quantity/rate grammar.

Task 3 (`test_unit_formatting.py`) owns simple-quantity, rate, label, null,
reciprocal-zero and forced-pair coverage; duplicating those here would test
code this module does not touch. This file is scoped to the two derived
formatters, their two presentation-scale constants, and the
cost-per-distance unit label.

Every expected string below is computed in THIS file from the real
adapter/counterpart machinery (`app.utils.unit_adapters.adapter_for`,
`app.utils.unit_counterparts.counterpart_for`) and the D4c flip rules, not
transcribed from the brief's illustrative grammar table. A wrong figure in
`unit_derived.py` therefore fails as a disagreement between two
independently written derivations, not as a mismatch against a pinned
string that might itself be the thing that is wrong.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.constants.units import IMPERIAL_PRESET, METRIC_PRESET, UnitSet
from app.utils.currency import get_currency_symbol
from app.utils.render_context import RenderContext
from app.utils.unit_adapters import UnitAdapter, adapter_for
from app.utils.unit_counterparts import counterpart_for
from app.utils.unit_derived import (
    PER_100_KM,
    PER_1000_MI,
    cost_per_distance_unit_label,
    format_cost_per_distance,
    format_fuel_rate,
)

# ---------------------------------------------------------------------------
# Fixtures: the four unit-set combinations the task names -- metric, US
# imperial, a mixed combination (gallons + kilometres, deliberately not a
# real preset), and a UK-gallon imperial variant.
# ---------------------------------------------------------------------------

_METRIC = METRIC_PRESET
_US_IMPERIAL = IMPERIAL_PRESET
_MIXED = UnitSet.model_validate(METRIC_PRESET.model_dump() | {"volume": "gal_us"})
_UK_GALLONS = UnitSet.model_validate(IMPERIAL_PRESET.model_dump() | {"volume": "gal_uk"})
_ALL_FIXTURES: dict[str, UnitSet] = {
    "metric": _METRIC,
    "us_imperial": _US_IMPERIAL,
    "mixed_gal_us_km": _MIXED,
    "uk_gallons": _UK_GALLONS,
}


def _ctx(units: UnitSet, show_both: bool) -> RenderContext:
    return RenderContext(units=units, show_both=show_both)


# ---------------------------------------------------------------------------
# Independent expectation builders. Each re-derives the composed string
# from the adapters and D4c's flip rule directly -- never by calling into
# unit_derived.py's own private helpers -- so a bug in unit_derived.py's
# composition (wrong adapter chosen for a side, wrong side scaled,
# to_display used where to_canonical(1) was needed, scale applied twice)
# shows up as a disagreement, not a tautology.
# ---------------------------------------------------------------------------


def _expected_fuel_rate(l_per_hr: Decimal, units: UnitSet, *, show_both: bool) -> str:
    """D4c: fuel rate flips volume only."""

    def side(adapter: UnitAdapter) -> str:
        display = adapter.to_display(l_per_hr)
        assert display is not None
        return f"{display:,.{adapter.precision}f} {adapter.label}/hr"

    primary = side(adapter_for(units, "volume"))
    if not show_both:
        return primary
    counterpart = counterpart_for(units, "volume")
    assert counterpart is not None
    return f"{primary} ({side(counterpart)})"


# Cost-per-distance's own scale convention, reproduced independently of
# unit_derived._COST_PER_DISTANCE_SCALE and of the PER_100_KM/PER_1000_MI
# constants imported above (which TestPresentationScales exercises
# directly, as its own golden test).
_EXPECTED_COST_PER_DISTANCE_SCALE = {"km": Decimal("100"), "mi": Decimal("1000")}


def _expected_cost_per_distance(
    cost_per_km: Decimal, units: UnitSet, symbol: str, *, show_both: bool
) -> str:
    """D4c: cost per distance flips distance and its presentation scale together.

    D5: the primary is plain money (its scale lives in the label), the
    counterpart keeps its own scale.
    """

    def side(adapter: UnitAdapter, *, with_scale: bool) -> str:
        factor = adapter.to_canonical(Decimal("1"))
        assert factor is not None
        scale = _EXPECTED_COST_PER_DISTANCE_SCALE[adapter.unit]
        value = cost_per_km * factor * scale
        figure = f"{symbol}{value:,.2f}"
        return f"{figure}/{scale:,.0f} {adapter.label}" if with_scale else figure

    primary = side(adapter_for(units, "distance"), with_scale=False)
    if not show_both:
        return primary
    counterpart = counterpart_for(units, "distance")
    assert counterpart is not None
    return f"{primary} ({side(counterpart, with_scale=True)})"


class TestPresentationScales:
    """R5: named presentation scales, not conversion factors -- each gets
    its own golden assertion on value and type."""

    def test_per_100_km(self) -> None:
        assert PER_100_KM == Decimal("100")

    def test_per_1000_mi(self) -> None:
        assert PER_1000_MI == Decimal("1000")

    def test_all_scales_are_decimal(self) -> None:
        """Global constraint: `Decimal`, never `float`. `int` would also
        compute correctly here but would violate composing cleanly with
        the `Decimal` canonical inputs these scales multiply against."""
        for scale in (PER_100_KM, PER_1000_MI):
            assert isinstance(scale, Decimal)


class TestFuelRate:
    """Canonical input: 2.5 L/hr. D4c: flips volume only."""

    @pytest.mark.parametrize("show_both", [False, True])
    @pytest.mark.parametrize("name", sorted(_ALL_FIXTURES))
    def test_matches_independent_computation(self, name: str, show_both: bool) -> None:
        units = _ALL_FIXTURES[name]
        canonical = Decimal("2.5")
        expected = _expected_fuel_rate(canonical, units, show_both=show_both)
        actual = format_fuel_rate(canonical, _ctx(units, show_both))
        assert actual == expected

    def test_null_short_circuits(self) -> None:
        assert format_fuel_rate(None, _ctx(_METRIC, True)) == "N/A"

    def test_zero_is_a_real_value_not_na(self) -> None:
        """Volume adapters are all Linear: zero litres per hour is a real,
        defined fuel rate (e.g. idling with the engine off), unlike a
        reciprocal adapter's undefined zero (Task 3's
        TestNullAndReciprocalZero). Guards against a `if not l_per_hr:`
        bug, which would treat `Decimal("0")` as falsy and short-circuit
        it to "N/A" too."""
        result = format_fuel_rate(Decimal("0"), _ctx(_METRIC, False))
        assert result == "0.00 L/hr"
        assert result != "N/A"

    def test_metric_and_imperial_actually_differ(self) -> None:
        """Two fixtures that happened to render the same string would not
        prove the volume side actually flips."""
        metric = format_fuel_rate(Decimal("2.5"), _ctx(_METRIC, False))
        imperial = format_fuel_rate(Decimal("2.5"), _ctx(_US_IMPERIAL, False))
        assert metric != imperial


class TestCostPerDistance:
    """Canonical input: 0.012 currency units per km. D4c: flips distance
    and its presentation scale together."""

    @pytest.mark.parametrize("show_both", [False, True])
    @pytest.mark.parametrize("name", sorted(_ALL_FIXTURES))
    def test_matches_independent_computation(self, name: str, show_both: bool) -> None:
        units = _ALL_FIXTURES[name]
        canonical = Decimal("0.012")
        symbol = get_currency_symbol("USD", "en-US")
        expected = _expected_cost_per_distance(canonical, units, symbol, show_both=show_both)
        actual = format_cost_per_distance(canonical, _ctx(units, show_both), "USD", "en-US")
        assert actual == expected

    def test_null_short_circuits(self) -> None:
        assert format_cost_per_distance(None, _ctx(_METRIC, True), "USD", "en-US") == "N/A"

    def test_zero_is_a_real_value_not_na(self) -> None:
        result = format_cost_per_distance(Decimal("0"), _ctx(_METRIC, False), "USD", "en-US")
        assert result == "$0.00"
        assert result != "N/A"

    def test_currency_code_is_resolved_to_its_symbol_not_embedded_literally(self) -> None:
        result = format_cost_per_distance(Decimal("0.012"), _ctx(_METRIC, False), "EUR", "en-US")
        assert get_currency_symbol("EUR", "en-US") in result
        assert "EUR" not in result

    def test_metric_and_imperial_actually_differ(self) -> None:
        metric = format_cost_per_distance(Decimal("0.012"), _ctx(_METRIC, False), "USD", "en-US")
        imperial = format_cost_per_distance(
            Decimal("0.012"), _ctx(_US_IMPERIAL, False), "USD", "en-US"
        )
        assert metric != imperial

    def test_cost_per_distance_is_independent_of_volume_choice(self) -> None:
        """D4c's flip rule for this quantity depends only on `distance`.
        The UK-gallon fixture shares `_US_IMPERIAL`'s distance (mi) but
        differs in `volume` -- the two must render identically here, or
        this function would be silently reading `ctx.units.volume`."""
        us = format_cost_per_distance(Decimal("0.012"), _ctx(_US_IMPERIAL, False), "USD", "en-US")
        uk = format_cost_per_distance(Decimal("0.012"), _ctx(_UK_GALLONS, False), "USD", "en-US")
        assert us == uk

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("metric", "100 km"),
            ("mixed_gal_us_km", "100 km"),
            ("us_imperial", "1,000 mi"),
            ("uk_gallons", "1,000 mi"),
        ],
    )
    def test_unit_label_names_the_readers_scale(self, name: str, expected: str) -> None:
        """D5: the label carries the primary's scale, read off distance only."""
        units = _ALL_FIXTURES[name]
        assert cost_per_distance_unit_label(_ctx(units, False)) == expected
        # show-both doesn't change it: the counterpart carries its own.
        assert cost_per_distance_unit_label(_ctx(units, True)) == expected

    def test_mile_reader_show_both_uses_the_brief_figures(self) -> None:
        """The brief's own figures: 0.42/km is 42.00 per 100 km and
        0.42 * 1.609344 * 1000 = 675.9245 per 1,000 mi."""
        ctx = _ctx(_US_IMPERIAL, True)
        assert cost_per_distance_unit_label(ctx) == "1,000 mi"
        assert format_cost_per_distance(Decimal("0.42"), ctx, "USD", "en-US") == (
            "$675.92 ($42.00/100 km)"
        )


class TestHandComputedGoldens:
    """Exact strings computed by hand, where a conversion factor is actually
    applied.

    Everything above this class compares `unit_derived.py` against an
    independent re-derivation. That catches a composition bug (wrong adapter
    for a side, wrong side scaled, scale applied twice) but not a wrong
    FACTOR: both sides recover the factor with the same
    `adapter.to_canonical(Decimal("1"))` call, so they move together.

    These are hand-typed literals off `UnitConverter`'s mile, which since
    v3.4.0 IS the ISO-exact 1.609344 km.

        cost per distance, canonical 0.012 per km (the primary drops its
        scale, D5; a counterpart keeps it)
          mi      0.012 * 1.609344 * 1000 = 19.312128 -> "$19.31", "$19.31/1,000 mi"
          km      0.012 * 1        *  100 =  1.2       -> "$1.20", "$1.20/100 km"
    """

    def test_cost_per_distance_imperial(self) -> None:
        actual = format_cost_per_distance(
            Decimal("0.012"), _ctx(_US_IMPERIAL, False), "USD", "en-US"
        )
        assert actual == "$19.31"

    def test_cost_per_distance_metric(self) -> None:
        """The identity side, pinned as a literal so the imperial golden
        above has a partner that fixes the scale convention too (100 km, not
        1,000 km)."""
        actual = format_cost_per_distance(Decimal("0.012"), _ctx(_METRIC, False), "USD", "en-US")
        assert actual == "$1.20"

    def test_cost_per_distance_show_both_imperial(self) -> None:
        """D4c: distance and scale flip together, so the counterpart is
        per 100 km, never per 1,000 km."""
        actual = format_cost_per_distance(
            Decimal("0.012"), _ctx(_US_IMPERIAL, True), "USD", "en-US"
        )
        assert actual == "$19.31 ($1.20/100 km)"

    def test_cost_per_distance_show_both_metric(self) -> None:
        actual = format_cost_per_distance(Decimal("0.012"), _ctx(_METRIC, True), "USD", "en-US")
        assert actual == "$1.20 ($19.31/1,000 mi)"

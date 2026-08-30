"""Derived-quantity formatting: fuel rate, cost per volume, cost per
distance, and volume per distance -- the four functions `unit_derived.py`
builds on top of `unit_formatting.py`'s simple-quantity/rate grammar.

Task 3 (`test_unit_formatting.py`) owns simple-quantity, rate, label, null,
reciprocal-zero and forced-pair coverage; duplicating those here would test
code this module does not touch. This file is scoped to the four derived
formatters plus their three presentation-scale constants.

Every expected string below is computed in THIS file from the real
adapter/counterpart machinery (`app.utils.unit_adapters.adapter_for`,
`app.utils.unit_counterparts.counterpart_for`) and the D4c flip rules, not
transcribed from the brief's illustrative grammar table -- see the brief's
own warning that two consecutive revisions of that table shipped arithmetic
errors, one of which (the mixed volume-per-distance show-both row) is
reproduced and flagged in `TestVolumePerDistanceMixedFlip` below. A wrong
figure in `unit_derived.py` therefore fails as a disagreement between two
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
    PER_1000_KM,
    PER_1000_MI,
    format_cost_per_distance,
    format_cost_per_volume,
    format_fuel_rate,
    format_volume_per_1000_distance,
)

# ---------------------------------------------------------------------------
# Fixtures: the four unit-set combinations the task names -- metric, US
# imperial, a mixed combination (gallons + kilometres, deliberately not a
# real preset: see TestVolumePerDistanceMixedFlip), and a UK-gallon
# imperial variant.
# ---------------------------------------------------------------------------

_METRIC = METRIC_PRESET
_US_IMPERIAL = IMPERIAL_PRESET
_MIXED = UnitSet.model_validate(METRIC_PRESET.model_dump() | {"volume": "gal_us"})
_UK_GALLONS = UnitSet.model_validate(IMPERIAL_PRESET.model_dump() | {"volume": "gal_uk"})
# A metric primary whose show-both counterpart gallon is the UK one (D4b:
# `L` states no flavour, so `secondary_gallon` supplies it). Deliberately
# NOT in `_ALL_FIXTURES` below: it exists to give the hand-computed goldens
# a case where a UK factor is applied on the COUNTERPART side, which none of
# the four fixtures above reaches.
_METRIC_UK_SECONDARY = UnitSet.model_validate(
    METRIC_PRESET.model_dump() | {"secondary_gallon": "uk"}
)

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


def _expected_cost_per_volume(
    cost_per_l: Decimal, units: UnitSet, symbol: str, *, show_both: bool
) -> str:
    """D4c: cost per volume flips volume only, no presentation scale."""

    def side(adapter: UnitAdapter) -> str:
        factor = adapter.to_canonical(Decimal("1"))
        assert factor is not None
        return f"{symbol}{cost_per_l * factor:,.2f}/{adapter.label}"

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
    """D4c: cost per distance flips distance and its presentation scale together."""

    def side(adapter: UnitAdapter) -> str:
        factor = adapter.to_canonical(Decimal("1"))
        assert factor is not None
        scale = _EXPECTED_COST_PER_DISTANCE_SCALE[adapter.unit]
        value = cost_per_km * factor * scale
        return f"{symbol}{value:,.2f}/{scale:,.0f} {adapter.label}"

    primary = side(adapter_for(units, "distance"))
    if not show_both:
        return primary
    counterpart = counterpart_for(units, "distance")
    assert counterpart is not None
    return f"{primary} ({side(counterpart)})"


# Volume-per-distance's own scale convention, reproduced independently of
# unit_derived._VOLUME_PER_DISTANCE_SCALE. km and mi share the numeric
# value 1000 here on purpose -- see the PER_1000_KM/PER_1000_MI docstrings.
_EXPECTED_VOLUME_PER_DISTANCE_SCALE = {"km": Decimal("1000"), "mi": Decimal("1000")}


def _expected_volume_per_distance(
    l_per_1000_km: Decimal, volume_adapter: UnitAdapter, distance_adapter: UnitAdapter
) -> str:
    """D4c: volume per distance flips BOTH sides, composed independently.

    Takes the two adapters directly, rather than a `UnitSet`, so a caller
    can build the primary pairing and a fully independent counterpart
    pairing with the same function -- in `TestVolumePerDistanceMixedFlip`
    the counterpart's volume and distance adapters are each their own
    fixed counterpart, not "the other fixture's primary pair".
    """
    per_canonical_km = l_per_1000_km / Decimal("1000")
    numerator = volume_adapter.to_display(per_canonical_km)
    assert numerator is not None
    denom_factor = distance_adapter.to_canonical(Decimal("1"))
    assert denom_factor is not None
    scale = _EXPECTED_VOLUME_PER_DISTANCE_SCALE[distance_adapter.unit]
    value = numerator * denom_factor * scale
    return (
        f"{value:,.{volume_adapter.precision}f} {volume_adapter.label}"
        f"/{scale:,.0f} {distance_adapter.label}"
    )


def _expected_volume_per_distance_show_both(
    l_per_1000_km: Decimal, units: UnitSet, *, show_both: bool
) -> str:
    primary = _expected_volume_per_distance(
        l_per_1000_km, adapter_for(units, "volume"), adapter_for(units, "distance")
    )
    if not show_both:
        return primary
    cp_volume = counterpart_for(units, "volume")
    cp_distance = counterpart_for(units, "distance")
    assert cp_volume is not None
    assert cp_distance is not None
    counterpart = _expected_volume_per_distance(l_per_1000_km, cp_volume, cp_distance)
    return f"{primary} ({counterpart})"


class TestPresentationScales:
    """R5: named presentation scales, not conversion factors -- each gets
    its own golden assertion on value and type."""

    def test_per_100_km(self) -> None:
        assert PER_100_KM == Decimal("100")

    def test_per_1000_km(self) -> None:
        assert PER_1000_KM == Decimal("1000")

    def test_per_1000_mi(self) -> None:
        assert PER_1000_MI == Decimal("1000")

    def test_all_scales_are_decimal(self) -> None:
        """Global constraint: `Decimal`, never `float`. `int` would also
        compute correctly here but would violate composing cleanly with
        the `Decimal` canonical inputs these scales multiply against."""
        for scale in (PER_100_KM, PER_1000_KM, PER_1000_MI):
            assert isinstance(scale, Decimal)

    def test_per_1000_km_and_per_1000_mi_are_declared_separately(self) -> None:
        """They intentionally share a numeric value (both are 1000) but
        name two different presentation conventions -- a km-based rate's
        scale and a mile-based rate's scale -- which is why both exist as
        named constants instead of one aliasing the other, and why
        PER_100_KM (a genuinely different value) is not interchangeable
        with either."""
        assert PER_1000_KM == PER_1000_MI
        assert PER_1000_KM != PER_100_KM


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


class TestCostPerVolume:
    """Canonical input: 0.32 currency units per litre. D4c: flips volume
    only, no presentation scale."""

    @pytest.mark.parametrize("show_both", [False, True])
    @pytest.mark.parametrize("name", sorted(_ALL_FIXTURES))
    def test_matches_independent_computation(self, name: str, show_both: bool) -> None:
        units = _ALL_FIXTURES[name]
        canonical = Decimal("0.32")
        symbol = get_currency_symbol("USD", "en-US")
        expected = _expected_cost_per_volume(canonical, units, symbol, show_both=show_both)
        actual = format_cost_per_volume(canonical, _ctx(units, show_both), "USD", "en-US")
        assert actual == expected

    def test_null_short_circuits(self) -> None:
        assert format_cost_per_volume(None, _ctx(_METRIC, True), "USD", "en-US") == "N/A"

    def test_zero_is_a_real_value_not_na(self) -> None:
        result = format_cost_per_volume(Decimal("0"), _ctx(_METRIC, False), "USD", "en-US")
        assert result == "$0.00/L"
        assert result != "N/A"

    def test_currency_code_is_resolved_to_its_symbol_not_embedded_literally(self) -> None:
        """The task's own requirement: currency is a code plus a locale,
        resolved through `get_currency_symbol` -- a pre-resolved symbol
        would drop the locale-aware contract. Distinguishes the CODE
        ("EUR") from the rendered SYMBOL ("<euro>") rather than asserting a
        string shape that could pass whichever one leaked through."""
        result = format_cost_per_volume(Decimal("0.32"), _ctx(_METRIC, False), "EUR", "en-US")
        assert get_currency_symbol("EUR", "en-US") in result
        assert "EUR" not in result

    def test_metric_and_imperial_actually_differ(self) -> None:
        metric = format_cost_per_volume(Decimal("0.32"), _ctx(_METRIC, False), "USD", "en-US")
        imperial = format_cost_per_volume(
            Decimal("0.32"), _ctx(_US_IMPERIAL, False), "USD", "en-US"
        )
        assert metric != imperial

    def test_currency_code_none_falls_back_to_usd_symbol(self) -> None:
        """`get_currency_symbol(None, ...)` falls back to `"$"` -- confirms
        this module threads a `None` code through to `get_currency_symbol`
        rather than crashing or embedding a literal "None"."""
        result = format_cost_per_volume(Decimal("0.32"), _ctx(_METRIC, False), None, "en-US")
        assert result == "$0.32/L"


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
        assert result == "$0.00/100 km"
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


class TestVolumePerDistance:
    """Canonical input: 8.5 L per 1,000 canonical km. D4c: flips BOTH
    numerator and denominator, composed independently."""

    @pytest.mark.parametrize("show_both", [False, True])
    @pytest.mark.parametrize("name", sorted(_ALL_FIXTURES))
    def test_matches_independent_computation(self, name: str, show_both: bool) -> None:
        units = _ALL_FIXTURES[name]
        canonical = Decimal("8.5")
        expected = _expected_volume_per_distance_show_both(canonical, units, show_both=show_both)
        actual = format_volume_per_1000_distance(canonical, _ctx(units, show_both))
        assert actual == expected

    def test_null_short_circuits(self) -> None:
        assert format_volume_per_1000_distance(None, _ctx(_METRIC, True)) == "N/A"

    def test_zero_is_a_real_value_not_na(self) -> None:
        result = format_volume_per_1000_distance(Decimal("0"), _ctx(_METRIC, False))
        assert result == "0.00 L/1,000 km"
        assert result != "N/A"

    def test_metric_and_mixed_differ_only_on_the_volume_side(self) -> None:
        """`_METRIC` and `_MIXED` share `distance="km"`; only `volume`
        differs (L vs gal_us). Confirms the volume side actually flips
        even when the distance side does not."""
        metric = format_volume_per_1000_distance(Decimal("8.5"), _ctx(_METRIC, False))
        mixed = format_volume_per_1000_distance(Decimal("8.5"), _ctx(_MIXED, False))
        assert metric != mixed
        assert metric.endswith("/1,000 km")
        assert mixed.endswith("/1,000 km")
        assert " L/" in metric
        assert " gal/" in mixed

    def test_mixed_and_us_imperial_differ_only_on_the_distance_side(self) -> None:
        """`_MIXED` and `_US_IMPERIAL` share `volume="gal_us"`; only
        `distance` differs (km vs mi). Confirms the distance side actually
        flips even when the volume side does not."""
        mixed = format_volume_per_1000_distance(Decimal("8.5"), _ctx(_MIXED, False))
        us_imperial = format_volume_per_1000_distance(Decimal("8.5"), _ctx(_US_IMPERIAL, False))
        assert mixed != us_imperial
        assert mixed.endswith("/1,000 km")
        assert us_imperial.endswith("/1,000 mi")
        assert mixed.split("/")[0].strip().endswith("gal")
        assert us_imperial.split("/")[0].strip().endswith("gal")


class TestVolumePerDistanceMixedFlip:
    """The scenario the brief calls out by name: a "gallons plus
    kilometres" fixture (volume=gal_us, distance=km -- not a real preset)
    proves D4c's "flips BOTH, composed independently" rule, and exposes
    where the brief's own illustrative table is wrong.

    v3's mutation testing could not kill its own volume-per-distance test
    because its fixture was already litres-primary: hardcoding the volume
    side to litres changed nothing about the expected output. Using
    gal_us+km here means hardcoding either side away from its real value
    changes what this fixture is supposed to render, so a regression on
    either side is caught -- see the mutation testing performed against
    this class, reported alongside this task.
    """

    def test_show_both_true_flips_both_sides_independently(self) -> None:
        """D4c: the counterpart here is NOT "flip distance only" or "flip
        volume only" -- it is L (volume's fixed counterpart of gal_us) AND
        mi (distance's fixed counterpart of km), composed together, i.e.
        litres per 1,000 MILES, not litres per 1,000 km."""
        canonical = Decimal("8.5")
        result = format_volume_per_1000_distance(canonical, _ctx(_MIXED, True))
        expected = _expected_volume_per_distance_show_both(canonical, _MIXED, show_both=True)
        assert result == expected

        # Prove the counterpart's distance side is genuinely mi, not km --
        # structurally, not just via the composed numeric string above.
        counterpart_distance = counterpart_for(_MIXED, "distance")
        assert counterpart_distance is not None
        assert counterpart_distance.unit == "mi"
        assert "(" in result
        counterpart_text = result.split("(", 1)[1].rstrip(")")
        assert counterpart_text.endswith(" mi")
        assert "km" not in counterpart_text

    def test_disagreement_with_the_illustrative_table(self) -> None:
        """The brief's own grammar table states this row's counterpart as
        "8.50 L/1,000 km" (only the volume side flipped) and explicitly
        flags that as one of two known arithmetic errors two consecutive
        review rounds introduced into that table -- the rule-correct
        counterpart (both sides flipped, per D4c) is "13.68 L/1,000 mi".
        This pins the computed-correct value the code under test actually
        produces and documents the table disagreement rather than silently
        reproducing it. 8.5 / 1000 = 0.0085 L/km; 0.0085 L/km is already
        the L/km rate (L's factor is 1); 0.0085 * 1.60934 (km per mile,
        UnitConverter.MILES_TO_KM) * 1000 = 13.679... -> "13.68"."""
        result = format_volume_per_1000_distance(Decimal("8.5"), _ctx(_MIXED, True))
        assert result == "2.25 gal/1,000 km (13.68 L/1,000 mi)"
        assert "(8.50 L/1,000 km)" not in result


class TestHandComputedGoldens:
    """Exact strings computed by hand, where a conversion factor is actually
    applied.

    Everything above this class compares `unit_derived.py` against an
    independent re-derivation. That catches a composition bug (wrong adapter
    for a side, wrong side scaled, scale applied twice) but not a wrong
    FACTOR: both sides recover the factor with the same
    `adapter.to_canonical(Decimal("1"))` call, so they move together. The
    only exact strings the file had were `"N/A"`, zeros, metric identities
    (factor 1) and one volume-per-distance row, which left
    `format_cost_per_volume` and `format_cost_per_distance` with no golden in
    which a factor is exercised at all, and left every gallon-flavoured
    volume-per-distance figure unpinned.

    These are hand-typed literals, derived below from the three constants and
    nothing else. `UnitConverter`'s values, not the ISO-exact ones:
    US gallon 3.78541 L, UK gallon 4.54609 L, mile 1.60934 km.

        cost per volume, canonical 0.32 per litre
          gal_us  0.32 * 3.78541 = 1.2113312  -> "$1.21/gal"
          gal_uk  0.32 * 4.54609 = 1.4547488  -> "$1.45/gal"
          L       0.32 * 1       = 0.32       -> "$0.32/L"

        cost per distance, canonical 0.012 per km
          mi      0.012 * 1.60934 * 1000 = 19.31208 -> "$19.31/1,000 mi"
          km      0.012 * 1       *  100 =  1.2     -> "$1.20/100 km"

        volume per distance, canonical 8.5 L per 1,000 km
          (8.5 / 1000 = 0.0085 L per canonical km)
          L      /1,000 km  0.0085 / 1       * 1       * 1000 =  8.500  -> "8.50"
          gal_us /1,000 mi  0.0085 / 3.78541 * 1.60934 * 1000 =  3.6137 -> "3.61"
          gal_uk /1,000 mi  0.0085 / 4.54609 * 1.60934 * 1000 =  3.0090 -> "3.01"

    The first three of these ($1.21/gal, $19.31/1,000 mi, and the fuel-rate
    pair 0.66/0.55 gal/hr that `test_unit_formatting.py` already carries) are
    the illustrative rows the plan asked to be spot-checked by hand; none of
    them appeared anywhere in this file before.
    """

    def test_cost_per_volume_us_gallon(self) -> None:
        actual = format_cost_per_volume(Decimal("0.32"), _ctx(_US_IMPERIAL, False), "USD", "en-US")
        assert actual == "$1.21/gal"

    def test_cost_per_volume_uk_gallon(self) -> None:
        """The same canonical value under a UK reader. The two gallon
        flavours share a label ("gal"), so only the NUMBER distinguishes
        them -- which is exactly why a golden is needed here and a
        label-shaped assertion would not do."""
        actual = format_cost_per_volume(Decimal("0.32"), _ctx(_UK_GALLONS, False), "USD", "en-US")
        assert actual == "$1.45/gal"

    def test_cost_per_volume_show_both_us(self) -> None:
        actual = format_cost_per_volume(Decimal("0.32"), _ctx(_US_IMPERIAL, True), "USD", "en-US")
        assert actual == "$1.21/gal ($0.32/L)"

    def test_cost_per_volume_show_both_uk(self) -> None:
        actual = format_cost_per_volume(Decimal("0.32"), _ctx(_UK_GALLONS, True), "USD", "en-US")
        assert actual == "$1.45/gal ($0.32/L)"

    def test_cost_per_volume_counterpart_takes_us_from_secondary_gallon(self) -> None:
        """D4b on the COUNTERPART side: a litre primary states no flavour, so
        `secondary_gallon` picks it. The factor is applied inside the
        parentheses here, where the primary is the identity."""
        actual = format_cost_per_volume(Decimal("0.32"), _ctx(_METRIC, True), "USD", "en-US")
        assert actual == "$0.32/L ($1.21/gal)"

    def test_cost_per_volume_counterpart_takes_uk_from_secondary_gallon(self) -> None:
        """The other flavour, same primary. Without this pair the counterpart
        gallon could be hardwired to US and every other assertion in the file
        would still pass."""
        actual = format_cost_per_volume(
            Decimal("0.32"), _ctx(_METRIC_UK_SECONDARY, True), "USD", "en-US"
        )
        assert actual == "$0.32/L ($1.45/gal)"

    def test_cost_per_distance_imperial(self) -> None:
        actual = format_cost_per_distance(
            Decimal("0.012"), _ctx(_US_IMPERIAL, False), "USD", "en-US"
        )
        assert actual == "$19.31/1,000 mi"

    def test_cost_per_distance_metric(self) -> None:
        """The identity side, pinned as a literal so the imperial golden
        above has a partner that fixes the scale convention too (100 km, not
        1,000 km)."""
        actual = format_cost_per_distance(Decimal("0.012"), _ctx(_METRIC, False), "USD", "en-US")
        assert actual == "$1.20/100 km"

    def test_cost_per_distance_show_both_imperial(self) -> None:
        """D4c: distance and scale flip together, so the counterpart is
        per 100 km, never per 1,000 km."""
        actual = format_cost_per_distance(
            Decimal("0.012"), _ctx(_US_IMPERIAL, True), "USD", "en-US"
        )
        assert actual == "$19.31/1,000 mi ($1.20/100 km)"

    def test_cost_per_distance_show_both_metric(self) -> None:
        actual = format_cost_per_distance(Decimal("0.012"), _ctx(_METRIC, True), "USD", "en-US")
        assert actual == "$1.20/100 km ($19.31/1,000 mi)"

    def test_volume_per_distance_us_gallons_per_1000_miles(self) -> None:
        """Both sides non-identity at once: the US gallon divides the
        numerator while the mile scales the denominator."""
        actual = format_volume_per_1000_distance(Decimal("8.5"), _ctx(_US_IMPERIAL, False))
        assert actual == "3.61 gal/1,000 mi"

    def test_volume_per_distance_uk_gallons_per_1000_miles(self) -> None:
        actual = format_volume_per_1000_distance(Decimal("8.5"), _ctx(_UK_GALLONS, False))
        assert actual == "3.01 gal/1,000 mi"

    def test_volume_per_distance_show_both_uk(self) -> None:
        actual = format_volume_per_1000_distance(Decimal("8.5"), _ctx(_UK_GALLONS, True))
        assert actual == "3.01 gal/1,000 mi (8.50 L/1,000 km)"

    def test_volume_per_distance_counterpart_takes_us_from_secondary_gallon(self) -> None:
        """Metric primary, so the whole conversion happens in the
        parentheses: gal_us AND mi together, per D4c's "flips BOTH"."""
        actual = format_volume_per_1000_distance(Decimal("8.5"), _ctx(_METRIC, True))
        assert actual == "8.50 L/1,000 km (3.61 gal/1,000 mi)"

    def test_volume_per_distance_counterpart_takes_uk_from_secondary_gallon(self) -> None:
        actual = format_volume_per_1000_distance(Decimal("8.5"), _ctx(_METRIC_UK_SECONDARY, True))
        assert actual == "8.50 L/1,000 km (3.01 gal/1,000 mi)"

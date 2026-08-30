"""Formatting layer: show-both grammar, the null/reciprocal-zero short
circuit, rates, labels, and the DEF forced volume pair.

Scoped to what Task 3 creates (the plan's own boundary): simple-quantity,
rate, label, null, reciprocal-zero, missing-counterpart, forced-pair and
`secondary_gallon` rows. The four derived-quantity rows (cost per volume,
cost per distance, fuel rate, volume per distance) belong to Task 4, which
creates those formatters; testing them here would be testing code that does
not exist yet.

Every expected string below is a hand-typed LITERAL, with the arithmetic
that produces it written out in the comment or docstring beside it, worked
from `UnitConverter`'s own constants (mile 1.60934 km, US gallon 3.78541 L,
UK gallon 4.54609 L). Deliberately literals rather than a re-derivation in
this file: an expectation computed from the same constant the code under
test uses moves with that constant instead of pinning it. They are equally
deliberately not transcribed from the brief's illustrative grammar table,
which shipped arithmetic errors in two consecutive revisions.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.constants.units import METRIC_PRESET, UnitSet
from app.utils.render_context import RenderContext
from app.utils.unit_formatting import (
    format_forced_volume_pair,
    format_label,
    format_quantity,
    format_rate,
)

# 1000 / 1.60934 = 621.3727... -> "621" at precision 0. Verified independently
# by hand: 621 * 1.60934 = 999.60 and 622 * 1.60934 = 1001.21, so 621 is the
# nearer whole number, matching the brief's illustrative row.
_MI_FOR_1000_KM = "621"


def _ctx(show_both: bool = False, **overrides: str) -> RenderContext:
    """A `RenderContext` built on the metric preset with `overrides` applied."""
    units = UnitSet.model_validate(METRIC_PRESET.model_dump() | overrides)
    return RenderContext(units=units, show_both=show_both)


class TestSimpleQuantity:
    """Canonical input: 1000 km. km/mi round to whole numbers (precision 0)."""

    def test_show_both_false_renders_primary_only(self) -> None:
        result = format_quantity(Decimal("1000"), _ctx(show_both=False), "distance")
        assert result == "1,000 km"

    def test_show_both_true_appends_the_counterpart(self) -> None:
        result = format_quantity(Decimal("1000"), _ctx(show_both=True), "distance")
        assert result == f"1,000 km ({_MI_FOR_1000_KM} mi)"

    def test_show_both_false_never_appends_a_counterpart(self) -> None:
        """Not just that the False case renders a shorter string -- that it
        contains no parenthesis at all, so a formatter that always computes
        the counterpart and only sometimes hides it can't sneak by."""
        result = format_quantity(Decimal("1000"), _ctx(show_both=False), "distance")
        assert "(" not in result


class TestNullAndReciprocalZero:
    """Both short-circuit to exactly `"N/A"`, with no counterpart, even when
    `show_both=True` -- proving the short-circuit happens before composition,
    not that composition merely renders `"N/A"` on one side."""

    def test_null_canonical_short_circuits(self) -> None:
        result = format_quantity(None, _ctx(show_both=True), "distance")
        assert result == "N/A"

    def test_reciprocal_zero_short_circuits(self) -> None:
        """`mpg_us` is an `InverseUnitAdapter`: canonical 0 means "infinite
        consumption per unit fuel", which is undefined, not zero MPG."""
        result = format_quantity(
            Decimal("0"), _ctx(show_both=True, consumption="mpg_us"), "consumption"
        )
        assert result == "N/A"


class TestMissingCounterpart:
    """Primary succeeds; the counterpart's own conversion is independently
    undefined. `l_100km` (Linear, factor 1) treats canonical 0 as a real,
    defined value (0.00 L/100km); its show-both counterpart under
    `secondary_gallon="us"` is `mpg_us` (Inverse), whose `to_display(0)` is
    undefined by division-by-zero. The composed string must still show the
    counterpart's own `"N/A"` in parentheses -- this is NOT the same
    short-circuit as a null/undefined PRIMARY, and collapsing the two would
    silently swallow this case's parenthetical entirely."""

    def test_counterpart_na_is_still_composed(self) -> None:
        ctx = _ctx(show_both=True, consumption="l_100km", secondary_gallon="us")
        result = format_quantity(Decimal("0"), ctx, "consumption")
        assert result == "0.00 L/100km (N/A)"

    def test_the_primary_alone_is_not_na(self) -> None:
        """Guards the test above against accidentally exercising the
        primary-undefined short circuit instead of a genuine missing
        counterpart."""
        ctx = _ctx(show_both=False, consumption="l_100km")
        result = format_quantity(Decimal("0"), ctx, "consumption")
        assert result == "0.00 L/100km"
        assert result != "N/A"


class TestSecondaryGallon:
    """A litre primary's show-both counterpart has no flavour of its own
    (D4b), so `secondary_gallon` supplies one. Canonical: 40 L.
    40 / 3.78541 = 10.5678... -> "10.57"; 40 / 4.54609 = 8.7995... -> "8.80"."""

    def test_us_secondary_gallon(self) -> None:
        ctx = _ctx(show_both=True, volume="L", secondary_gallon="us")
        result = format_quantity(Decimal("40"), ctx, "volume")
        assert result == "40.00 L (10.57 gal)"

    def test_uk_secondary_gallon(self) -> None:
        ctx = _ctx(show_both=True, volume="L", secondary_gallon="uk")
        result = format_quantity(Decimal("40"), ctx, "volume")
        assert result == "40.00 L (8.80 gal)"

    def test_the_two_flavours_actually_differ(self) -> None:
        """Two settings that happen to agree would prove nothing (same
        reasoning `test_unit_counterparts.py` uses for the D4b precedence
        tests)."""
        us_result = format_quantity(
            Decimal("40"), _ctx(show_both=True, volume="L", secondary_gallon="us"), "volume"
        )
        uk_result = format_quantity(
            Decimal("40"), _ctx(show_both=True, volume="L", secondary_gallon="uk"), "volume"
        )
        assert us_result != uk_result


class TestRate:
    """The suffix is applied to EACH representation independently. Naively
    appending it to a completed show-both string would yield
    `"1,000 km (621 mi)/mo"`, stating neither rate correctly."""

    def test_show_both_false(self) -> None:
        result = format_rate(Decimal("1000"), _ctx(show_both=False), "distance", "/mo")
        assert result == "1,000 km/mo"

    def test_show_both_true_suffixes_both_sides(self) -> None:
        result = format_rate(Decimal("1000"), _ctx(show_both=True), "distance", "/mo")
        assert result == f"1,000 km/mo ({_MI_FOR_1000_KM} mi/mo)"
        # The naive, wrong composition this guards against:
        assert result != f"1,000 km ({_MI_FOR_1000_KM} mi)/mo"

    def test_null_short_circuits_with_no_suffix(self) -> None:
        result = format_rate(None, _ctx(show_both=True), "distance", "/mo")
        assert result == "N/A"


class TestLabel:
    """The primary adapter's label alone -- never parenthesised, never
    composed with a counterpart, and independent of `show_both`."""

    def test_returns_the_primary_label(self) -> None:
        assert format_label(_ctx(), "distance") == "km"

    @pytest.mark.parametrize("show_both", [True, False])
    def test_unaffected_by_show_both(self, show_both: bool) -> None:
        """Both states, not one: a name claiming independence that samples
        only the default `show_both=False` would not prove independence at
        all -- it would just never have touched the flag."""
        assert format_label(_ctx(show_both=show_both), "distance") == "km"

    def test_never_parenthesised_or_composed(self) -> None:
        result = format_label(_ctx(show_both=True), "distance")
        assert "(" not in result
        assert result == "km"


class TestForcedVolumePair:
    """DEF's forced dual representation: always litres-then-gallons,
    independent of `show_both`, with the gallon flavour chosen by D4b
    precedence rather than the show-both counterpart table. Canonical: 2.5 L.
    2.5 / 3.78541 = 0.660430... -> "0.66"; 2.5 / 4.54609 = 0.549923... ->
    "0.55". Preserves the live string's separator: `" / "`, single spaces,
    no surrounding parenthesis or "remaining" text (that belongs to the
    dispatcher's own message template, Task 6)."""

    def test_null_short_circuits(self) -> None:
        assert format_forced_volume_pair(None, _ctx(volume="L")) == "N/A"

    def test_litre_primary_us_secondary(self) -> None:
        ctx = _ctx(volume="L", secondary_gallon="us")
        assert format_forced_volume_pair(Decimal("2.5"), ctx) == "2.50 L / 0.66 gal"

    def test_litre_primary_uk_secondary(self) -> None:
        ctx = _ctx(volume="L", secondary_gallon="uk")
        assert format_forced_volume_pair(Decimal("2.5"), ctx) == "2.50 L / 0.55 gal"

    def test_gal_uk_primary_wins_over_us_secondary(self) -> None:
        """Conflict direction 1: a UK-gallon primary beats a US
        `secondary_gallon`, because the primary states its own flavour."""
        ctx = _ctx(volume="gal_uk", secondary_gallon="us")
        assert format_forced_volume_pair(Decimal("2.5"), ctx) == "2.50 L / 0.55 gal"

    def test_gal_us_primary_wins_over_uk_secondary(self) -> None:
        """Conflict direction 2: the reverse pairing. Testing only the
        agreeing case (or only one direction) would not distinguish D4b's
        real precedence rule from "always use `secondary_gallon`" or
        "always use the primary" -- both of which pass one direction and
        fail the other."""
        ctx = _ctx(volume="gal_us", secondary_gallon="uk")
        assert format_forced_volume_pair(Decimal("2.5"), ctx) == "2.50 L / 0.66 gal"

    @pytest.mark.parametrize("show_both", [True, False])
    def test_unaffected_by_show_both(self, show_both: bool) -> None:
        """Not `format_quantity` with a flag: DEF emits both units always."""
        ctx = _ctx(show_both=show_both, volume="L", secondary_gallon="us")
        assert format_forced_volume_pair(Decimal("2.5"), ctx) == "2.50 L / 0.66 gal"

"""
Unit tests for unit conversion utilities.

Tests the canonical write path, `miles_to_km`, the factor table and gallon flavour.
"""

import asyncio
from decimal import Decimal

import pytest

from app.utils.units import GallonFlavour, UnitConverter


@pytest.mark.unit
class TestUnitConverterHelpers:
    """Test helper methods."""

    def test_to_decimal_with_int(self):
        """Test converting int to Decimal."""
        result = UnitConverter.to_decimal(100)
        assert result == Decimal("100")

    def test_to_decimal_with_float(self):
        """Test converting float to Decimal."""
        result = UnitConverter.to_decimal(100.5)
        assert result == Decimal("100.5")

    def test_to_decimal_with_decimal(self):
        """Test that Decimal passes through unchanged."""
        original = Decimal("100.5")
        result = UnitConverter.to_decimal(original)
        assert result == original

    def test_to_decimal_with_none(self):
        """Test that None returns None."""
        result = UnitConverter.to_decimal(None)
        assert result is None

    def test_round_result(self):
        """Test rounding and float conversion."""
        result = UnitConverter.round_result(Decimal("123.456"), 2)
        assert result == 123.46

    def test_round_result_with_none(self):
        """Test that None returns None."""
        result = UnitConverter.round_result(None)
        assert result is None


@pytest.mark.unit
class TestDistanceConversions:
    """`miles_to_km`, the one float helper left (mile odometer readings)."""

    def test_miles_to_km(self):
        """Test miles to kilometers conversion."""
        result = UnitConverter.miles_to_km(100)
        assert result == pytest.approx(160.93, rel=0.01)

    def test_miles_to_km_with_none(self):
        """Test None handling."""
        assert UnitConverter.miles_to_km(None) is None


@pytest.mark.unit
class TestDecimalPrecision:
    """Test that Decimal precision is maintained."""

    def test_float_input_precision(self):
        """Test that float inputs are converted properly."""
        result = UnitConverter.miles_to_km(100.5)
        assert isinstance(result, float)
        assert result == pytest.approx(161.74, rel=0.01)


@pytest.mark.unit
class TestGoldenConversions:
    """Absolute conversions pinned to known-correct values.

    Round-trip tests (`to_display(to_canonical(x)) == x`) pass against a wrong
    factor because both directions share it. These assert the factor itself.
    """

    def test_psi_canonicalises_to_kpa_not_bar(self) -> None:
        # 1 PSI == 6.894757293168361336722673445 kPa (0.45359237 * 9.80665 /
        # 0.0254**2 / 1000). Returning the /100 value means bar was emitted.
        assert UnitConverter.to_canonical_decimal(1, "PSI") == Decimal(
            "6.894757293168361336722673445"
        )

    @pytest.mark.parametrize(
        ("value", "from_unit", "expected"),
        [
            (1, "mi", Decimal("1.609344")),
            (1, "ft", Decimal("0.3048")),
            (1, "lb", Decimal("0.45359237")),
            (1, "lbft", Decimal("1.3558179483314004")),
            (32, "F", Decimal("0")),
            (1, "kPa", Decimal("1")),
        ],
    )
    def test_golden_absolute_conversions(
        self, value: float, from_unit: str, expected: Decimal
    ) -> None:
        result = UnitConverter.to_canonical_decimal(value, from_unit)
        assert result is not None
        # These factors are all exactly representable in Decimal, and this
        # test's whole purpose is pinning factor exactness -- an approx/float
        # comparison would let a wrong-but-close factor slip through.
        assert result == expected


async def _convert_after_yield(gallons: int, flavour: GallonFlavour) -> Decimal | None:
    """Perform one gallons-to-liters conversion with real yield points around it.

    Mimics one coroutine's slice of concurrent request handling: yield to the
    event loop (letting other coroutines' calls interleave), convert, then
    yield again. `flavour` is a local variable closed over by this coroutine,
    never shared -- that's exactly the property under test.
    """
    await asyncio.sleep(0)
    result = UnitConverter.to_canonical_decimal(gallons, "gal", flavour=flavour)
    await asyncio.sleep(0)
    return result


@pytest.mark.unit
class TestGallonFlavour:
    """Gallon flavour is an argument, never ambient class state."""

    def test_us_is_the_default(self) -> None:
        assert UnitConverter.to_canonical_decimal(1, "gal") == Decimal("3.785411784")

    def test_uk_gallon_is_larger(self) -> None:
        assert UnitConverter.to_canonical_decimal(1, "gal", flavour="uk") == Decimal("4.54609")
        assert UnitConverter.to_canonical_decimal(1, "gal", flavour="us") == Decimal("3.785411784")

    def test_mpg_numerator_follows_flavour(self) -> None:
        us = UnitConverter.to_canonical_decimal(30, "MPG", flavour="us")
        uk = UnitConverter.to_canonical_decimal(30, "MPG", flavour="uk")
        assert us is not None and uk is not None
        assert us == UnitConverter.US_MPG_TO_L100KM_NUMERATOR / 30
        assert uk == UnitConverter.UK_MPG_TO_L100KM_NUMERATOR / 30
        # 7.84 and 9.42 L/100km: a 30 MPG reading on the wrong gallon is 20% off.
        assert round(us, 2) == Decimal("7.84")
        assert round(uk, 2) == Decimal("9.42")

    @pytest.mark.asyncio
    async def test_interleaved_concurrent_conversions_keep_each_callers_flavour(self) -> None:
        """Genuinely concurrent conversions never cross-contaminate flavour.

        Runs 20 coroutines (alternating us/uk) through `asyncio.gather`, each
        yielding to the event loop both before and after its own conversion so
        the others' calls actually interleave around it -- not three
        sequential synchronous calls. Each coroutine must get the value
        correct for ITS OWN flavour, not merely a value that differs from its
        neighbours'. With class-level ambient state, a coroutine resuming
        after another had set a different flavour would pick up the wrong
        factor; with flavour as a parameter closed over per-coroutine, it
        cannot.
        """
        flavours: list[GallonFlavour] = ["us", "uk"] * 10
        results = await asyncio.gather(*(_convert_after_yield(1, flavour) for flavour in flavours))
        expected = {"us": Decimal("3.785411784"), "uk": Decimal("4.54609")}
        for flavour, result in zip(flavours, results, strict=True):
            assert result == expected[flavour], (
                f"flavour {flavour!r} produced {result}: another coroutine's flavour leaked "
                "into this concurrent conversion"
            )

    def test_mutable_class_state_is_gone(self) -> None:
        assert not hasattr(UnitConverter, "GALLONS_TO_LITERS")
        assert not hasattr(UnitConverter, "MPG_TO_L100KM_NUMERATOR")
        assert not hasattr(UnitConverter, "set_gallon_standard")
        assert not hasattr(UnitConverter, "get_gallon_standard")


class TestExactFactors:
    """Each factor against its legal definition, written out by hand here.

    Base factors are exact decimals and must be EQUAL. Derived factors whose
    exact value does not terminate are compared within 1e-24, far below any
    stored precision, so the test does not pin Decimal's 28-digit rounding.
    """

    def test_base_factors_are_the_definitions(self) -> None:
        assert UnitConverter.MILES_TO_KM == Decimal("1.609344")
        assert UnitConverter.FEET_TO_METERS == Decimal("0.3048")
        assert UnitConverter.INCH_TO_METERS == Decimal("0.0254")
        assert UnitConverter.US_GALLONS_TO_LITERS == Decimal("3.785411784")
        assert UnitConverter.UK_GALLONS_TO_LITERS == Decimal("4.54609")
        assert UnitConverter.LBS_TO_KG == Decimal("0.45359237")
        assert UnitConverter.STANDARD_GRAVITY == Decimal("9.80665")

    def test_terminating_derived_factors_are_exact(self) -> None:
        assert UnitConverter.LBF_TO_N == Decimal("4.4482216152605")
        assert UnitConverter.LBFT_TO_NM == Decimal("1.3558179483314004")

    def test_non_terminating_derived_factors_are_within_1e24(self) -> None:
        tolerance = Decimal("1e-24")
        # 4.4482216152605 / 0.00064516 / 1000
        assert (
            abs(UnitConverter.PSI_TO_KPA - Decimal("6.89475729316836133672267344535")) < tolerance
        )
        # 378.5411784 / 1.609344 and 454.609 / 1.609344
        assert (
            abs(
                UnitConverter.US_MPG_TO_L100KM_NUMERATOR
                - Decimal("235.214583333333333333333333333")
            )
            < tolerance
        )
        assert (
            abs(
                UnitConverter.UK_MPG_TO_L100KM_NUMERATOR
                - Decimal("282.480936331822158593812137119")
            )
            < tolerance
        )

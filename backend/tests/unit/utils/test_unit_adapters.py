"""Conversion layer: independent expectations, both directions, null and zero."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.constants.units import IMPERIAL_PRESET, METRIC_PRESET, UNIT_FIELD_NAMES, UnitSet
from app.utils.unit_adapters import ADAPTERS, adapter_for

# token -> (label, precision, canonical value of ONE typed unit; None = affine)
EXPECTED: dict[str, tuple[str, int, str | None]] = {
    "km": ("km", 0, "1"),
    "mi": ("mi", 0, "1.60934"),
    "kmh": ("km/h", 0, "1"),
    "mph": ("mph", 0, "1.60934"),
    "m": ("m", 2, "1"),
    "ft": ("ft", 2, "0.3048"),
    "L": ("L", 2, "1"),
    "gal_us": ("gal", 2, "3.78541"),
    "gal_uk": ("gal", 2, "4.54609"),
    "l_100km": ("L/100km", 2, "1"),
    "km_l": ("km/L", 2, "100"),
    "mpg_us": ("MPG", 1, "235.214"),
    "mpg_uk": ("MPG", 1, "282.481"),
    "kpa": ("kPa", 0, "1"),
    "bar": ("bar", 2, "100"),
    "psi": ("PSI", 1, "6.89476"),
    "c": ("C", 1, "1"),
    "f": ("F", 1, None),
    "kg": ("kg", 2, "1"),
    "lb": ("lb", 2, "0.45359237"),
    "nm": ("Nm", 1, "1"),
    "lbft": ("lb-ft", 1, "1.35582"),
    "mm": ("mm", 2, "1"),
    "in32": ("/32 in", 0, "0.79375"),
}
RECIPROCAL = ["km_l", "mpg_us", "mpg_uk"]


class TestAgainstIndependentExpectations:
    def test_same_tokens(self) -> None:
        assert set(ADAPTERS) == set(EXPECTED)

    @pytest.mark.parametrize("token", sorted(EXPECTED))
    def test_label(self, token: str) -> None:
        assert ADAPTERS[token].label == EXPECTED[token][0]

    @pytest.mark.parametrize("token", sorted(EXPECTED))
    def test_precision(self, token: str) -> None:
        assert ADAPTERS[token].precision == EXPECTED[token][1]

    @pytest.mark.parametrize("token", sorted(EXPECTED))
    def test_to_canonical_of_one(self, token: str) -> None:
        expected = EXPECTED[token][2]
        if expected is None:
            pytest.skip("affine, see TestAffine")
        assert ADAPTERS[token].to_canonical(Decimal("1")) == pytest.approx(
            Decimal(expected), rel=Decimal("1e-9")
        )

    @pytest.mark.parametrize("token", sorted(EXPECTED))
    def test_to_display_is_the_other_direction(self, token: str) -> None:
        """Round-3 finding: the golden table exercised only to_canonical, so a
        to_display that MULTIPLIES instead of dividing passed for mi, ft, gal,
        psi, lb and torque. Feed it the canonical value of one typed unit and
        require one back."""
        expected = EXPECTED[token][2]
        if expected is None:
            pytest.skip("affine, see TestAffine")
        assert ADAPTERS[token].to_display(Decimal(expected)) == pytest.approx(
            Decimal("1"), rel=Decimal("1e-9")
        )

    @pytest.mark.parametrize("token", sorted(EXPECTED))
    def test_key_is_the_token(self, token: str) -> None:
        assert ADAPTERS[token].unit == token


class TestAffine:
    @pytest.mark.parametrize(
        ("f", "c"), [("32", "0"), ("212", "100"), ("-40", "-40"), ("98.6", "37")]
    )
    def test_to_canonical(self, f: str, c: str) -> None:
        assert ADAPTERS["f"].to_canonical(Decimal(f)) == pytest.approx(
            Decimal(c), abs=Decimal("1e-9")
        )

    @pytest.mark.parametrize(
        ("c", "f"), [("0", "32"), ("100", "212"), ("-40", "-40"), ("37", "98.6")]
    )
    def test_to_display(self, c: str, f: str) -> None:
        """Several points, not one. A Fahrenheit adapter returning a constant 32
        passes a single-point check."""
        assert ADAPTERS["f"].to_display(Decimal(c)) == pytest.approx(
            Decimal(f), abs=Decimal("1e-6")
        )


class TestReciprocal:
    @pytest.mark.parametrize("token", RECIPROCAL)
    def test_doubling_typed_halves_canonical(self, token: str) -> None:
        """A zero-guarded LINEAR implementation passes every other check."""
        a = ADAPTERS[token].to_canonical(Decimal("30"))
        b = ADAPTERS[token].to_canonical(Decimal("60"))
        assert b == pytest.approx(a / 2, rel=Decimal("1e-9"))

    @pytest.mark.parametrize("token", RECIPROCAL)
    def test_display_is_also_reciprocal(self, token: str) -> None:
        a = ADAPTERS[token].to_display(Decimal("30"))
        b = ADAPTERS[token].to_display(Decimal("60"))
        assert b == pytest.approx(a / 2, rel=Decimal("1e-9"))

    @pytest.mark.parametrize(
        ("token", "typed", "canonical"),
        [("mpg_us", "30", "7.8405"), ("mpg_uk", "30", "9.4160"), ("km_l", "10", "10")],
    )
    def test_known_points(self, token: str, typed: str, canonical: str) -> None:
        assert ADAPTERS[token].to_canonical(Decimal(typed)) == pytest.approx(
            Decimal(canonical), rel=Decimal("1e-4")
        )

    def test_uk_and_us_differ(self) -> None:
        assert ADAPTERS["mpg_us"].to_canonical(Decimal("30")) != ADAPTERS["mpg_uk"].to_canonical(
            Decimal("30")
        )


class TestNullAndZero:
    @pytest.mark.parametrize("token", sorted(EXPECTED))
    def test_none_in_none_out(self, token: str) -> None:
        assert ADAPTERS[token].to_display(None) is None
        assert ADAPTERS[token].to_canonical(None) is None

    @pytest.mark.parametrize("token", sorted(EXPECTED))
    def test_format_of_none_is_na(self, token: str) -> None:
        assert ADAPTERS[token].format(None) == "N/A"

    @pytest.mark.parametrize("token", RECIPROCAL)
    def test_reciprocal_zero_is_undefined(self, token: str) -> None:
        """Both directions. Checking only to_canonical lets a broken to_display
        survive whenever format() happens to carry its own guard."""
        assert ADAPTERS[token].to_canonical(Decimal("0")) is None
        assert ADAPTERS[token].to_display(Decimal("0")) is None
        assert ADAPTERS[token].format(Decimal("0")) == "N/A"

    @pytest.mark.parametrize("token", ["km", "L", "kg", "c", "mm", "f"])
    def test_zero_is_a_real_value_for_linear_and_affine(self, token: str) -> None:
        """`f` is the only genuinely AFFINE adapter, and v4's version of this
        test omitted it, so the name claimed a property the body never reached.
        0 F is -17.8 C and 0 C is 32 F: both defined, neither missing."""
        assert ADAPTERS[token].to_canonical(Decimal("0")) is not None
        assert ADAPTERS[token].to_display(Decimal("0")) is not None
        assert ADAPTERS[token].format(Decimal("0")) != "N/A"


class TestFormatting:
    def test_grouping(self) -> None:
        assert ADAPTERS["km"].format(Decimal("12345")) == "12,345 km"

    def test_distance_has_no_decimal(self) -> None:
        assert ADAPTERS["km"].format(Decimal("10000")) == "10,000 km"

    def test_exact_consumption_strings(self) -> None:
        """Exact, not `in` or `startswith`: "7.840 L/100km" contains "7.84"."""
        assert ADAPTERS["l_100km"].format(Decimal("7.836")) == "7.84 L/100km"
        assert ADAPTERS["mpg_us"].format(Decimal("7.8405")) == "30.0 MPG"

    @pytest.mark.parametrize(
        ("token", "canonical", "expected"),
        [
            ("psi", "206.843", "30.0 PSI"),
            ("kpa", "206.843", "207 kPa"),
            ("bar", "206.843", "2.07 bar"),
            ("mi", "160.934", "100 mi"),
            ("lb", "45.359237", "100.00 lb"),
        ],
    )
    def test_exact_formatted_strings(self, token: str, canonical: str, expected: str) -> None:
        """Exact whole-string output, independent of `adapter.label`. Without
        this, a formatter hardcoding a wrong suffix passes every label test,
        which is why v4's claim that a PSI label change fails "the format test"
        was not actually true of any test it contained."""
        assert ADAPTERS[token].format(Decimal(canonical)) == expected

    def test_tread_keeps_two_decimals(self) -> None:
        assert ADAPTERS["mm"].format(Decimal("7.55")) == "7.55 mm"

    def test_slash_label_suppresses_the_space(self) -> None:
        assert ADAPTERS["in32"].format(Decimal("7.14375")) == "9/32 in"

    def test_without_label(self) -> None:
        assert ADAPTERS["km"].format(Decimal("12345"), with_label=False) == "12,345"


class TestCoverage:
    def test_every_vocabulary_value_has_an_adapter(self) -> None:
        from typing import get_args

        checked, missing = 0, []
        for name, field in UnitSet.model_fields.items():
            if name == "secondary_gallon":
                continue
            for value in get_args(field.annotation):
                checked += 1
                if value not in ADAPTERS:
                    missing.append(f"{name}={value}")
        assert checked == 24, f"scan inspected {checked}, expected 24"
        assert missing == []


class TestAdapterFor:
    def test_custom_set_resolves_per_quantity(self) -> None:
        mixed = UnitSet.model_validate(METRIC_PRESET.model_dump() | {"pressure": "psi"})
        assert adapter_for(mixed, "distance").unit == "km"
        assert adapter_for(mixed, "pressure").unit == "psi"

    @pytest.mark.parametrize("quantity", [q for q in UNIT_FIELD_NAMES if q != "secondary_gallon"])
    def test_every_quantity_under_both_presets(self, quantity: str) -> None:
        """Assert the resolved adapter IS the preset's token, not merely that
        something came back. `is not None` passes for a wrong-but-valid
        dispatch, which is the failure mode worth catching: identity is checked
        elsewhere for only two of the ten quantities."""
        for preset in (METRIC_PRESET, IMPERIAL_PRESET):
            assert adapter_for(preset, quantity).unit == getattr(preset, quantity)

    def test_unknown_quantity_raises(self) -> None:
        with pytest.raises(KeyError):
            adapter_for(METRIC_PRESET, "not_a_quantity")

    def test_hours_is_not_a_unit_quantity(self) -> None:
        """R6: due_hours is dimensionless and has no adapter. An implementer
        following an all-sites rule would call this and get a confusing KeyError
        at render time instead of here."""
        with pytest.raises(KeyError):
            adapter_for(METRIC_PRESET, "hours")

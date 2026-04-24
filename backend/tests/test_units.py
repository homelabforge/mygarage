"""Tests for the canonical unit conversion utility.

Covers the new SI-metric write path (to_canonical_decimal) plus regression
checks on the existing display-time conversions to make sure the canonical
flip didn't change their math.
"""

from decimal import Decimal

import pytest

from app.utils.units import UnitConverter


class TestToCanonicalDecimal:
    def test_km_passthrough(self) -> None:
        assert UnitConverter.to_canonical_decimal(148761, "km") == Decimal("148761")

    def test_miles_to_km_decimal_safe(self) -> None:
        # 92437 mi * 1.60934 = 148762.56158 — full precision retained
        result = UnitConverter.to_canonical_decimal(92437, "mi")
        assert result == Decimal("92437") * Decimal("1.60934")

    def test_liters_passthrough_preserves_decimal(self) -> None:
        # User types 37.854 → must round-trip exactly (issue #67's repro case)
        result = UnitConverter.to_canonical_decimal("37.854", "L")
        assert result == Decimal("37.854")

    def test_gallons_to_liters(self) -> None:
        result = UnitConverter.to_canonical_decimal(10, "gal")
        assert result == Decimal("10") * Decimal("3.78541")

    def test_lb_to_kg_uses_full_precision_factor(self) -> None:
        # Migration 053 uses 0.45359237 (not the older 0.453592 truncation).
        result = UnitConverter.to_canonical_decimal(7500, "lb")
        assert result == Decimal("7500") * Decimal("0.45359237")

    def test_ft_to_m(self) -> None:
        result = UnitConverter.to_canonical_decimal(16, "ft")
        assert result == Decimal("16") * Decimal("0.3048")

    def test_fahrenheit_to_celsius(self) -> None:
        # 32°F → 0°C, 212°F → 100°C
        assert UnitConverter.to_canonical_decimal(32, "F") == Decimal("0")
        assert UnitConverter.to_canonical_decimal(212, "F") == Decimal("100")

    def test_psi_to_bar(self) -> None:
        result = UnitConverter.to_canonical_decimal(30, "PSI")
        assert result == Decimal("30") * Decimal("0.0689476")

    def test_mpg_to_l_per_100km(self) -> None:
        # 18 MPG → 235.214 / 18
        result = UnitConverter.to_canonical_decimal(18, "MPG")
        assert result == Decimal("235.214") / Decimal("18")

    def test_mpg_zero_returns_none(self) -> None:
        # Avoid divide-by-zero for unset window-sticker spec values.
        assert UnitConverter.to_canonical_decimal(0, "MPG") is None

    def test_none_passthrough(self) -> None:
        assert UnitConverter.to_canonical_decimal(None, "km") is None
        assert UnitConverter.to_canonical_decimal(None, "MPG") is None

    def test_unknown_unit_raises(self) -> None:
        # Catches typos at call sites — better to fail loudly than silently
        # store a wrong-unit value.
        with pytest.raises(ValueError, match="Unknown source unit"):
            UnitConverter.to_canonical_decimal(10, "furlongs")

    @pytest.mark.parametrize(
        "value,unit",
        [
            ("12.345", "km"),
            ("12.345", "L"),
            ("12.345", "kg"),
            ("12.345", "m"),
            ("23.5", "C"),
            ("250.5", "kPa"),
            ("180.0", "Nm"),
            ("8.4", "L/100km"),
        ],
    )
    def test_metric_already_passthrough(self, value: str, unit: str) -> None:
        # Metric inputs must NOT be modified — preserve user precision exactly.
        result = UnitConverter.to_canonical_decimal(value, unit)
        assert result == Decimal(value)


class TestDisplayConversionsUnchanged:
    """Regression: the existing float-returning helpers still produce the
    same display values they did pre-flip. These methods are still used by
    UI rendering and PDF generators."""

    def test_gallons_to_liters(self) -> None:
        assert UnitConverter.gallons_to_liters(10) == 37.85

    def test_miles_to_km(self) -> None:
        assert UnitConverter.miles_to_km(100) == 160.93

    def test_celsius_to_fahrenheit(self) -> None:
        assert UnitConverter.celsius_to_fahrenheit(0) == 32.0
        assert UnitConverter.celsius_to_fahrenheit(100) == 212.0

    def test_round_result_returns_float(self) -> None:
        # Display path returns float (JSON-serializable)
        result = UnitConverter.round_result(Decimal("123.4567"))
        assert isinstance(result, float)
        assert result == 123.46

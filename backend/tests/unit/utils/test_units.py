"""
Unit tests for unit conversion utilities.

Tests imperial/metric conversions for volume, distance, fuel economy, etc.
"""

from decimal import Decimal

import pytest

from app.utils.units import UnitConverter


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
class TestVolumeConversions:
    """Test volume conversions (gallons/liters)."""

    def test_gallons_to_liters(self):
        """Test gallons to liters conversion."""
        result = UnitConverter.gallons_to_liters(10)
        assert result == pytest.approx(37.85, rel=0.01)

    def test_liters_to_gallons(self):
        """Test liters to gallons conversion."""
        result = UnitConverter.liters_to_gallons(37.85)
        assert result == pytest.approx(10.0, rel=0.01)

    def test_gallons_to_liters_roundtrip(self):
        """Test that conversion roundtrips correctly."""
        original = 15.0
        liters = UnitConverter.gallons_to_liters(original)
        back = UnitConverter.liters_to_gallons(liters)
        assert back == pytest.approx(original, rel=0.01)

    def test_gallons_to_liters_with_none(self):
        """Test None handling."""
        assert UnitConverter.gallons_to_liters(None) is None
        assert UnitConverter.liters_to_gallons(None) is None


@pytest.mark.unit
class TestDistanceConversions:
    """Test distance conversions (miles/km)."""

    def test_miles_to_km(self):
        """Test miles to kilometers conversion."""
        result = UnitConverter.miles_to_km(100)
        assert result == pytest.approx(160.93, rel=0.01)

    def test_km_to_miles(self):
        """Test kilometers to miles conversion."""
        result = UnitConverter.km_to_miles(160.93)
        assert result == pytest.approx(100.0, rel=0.01)

    def test_miles_to_km_roundtrip(self):
        """Test that conversion roundtrips correctly."""
        original = 250.0
        km = UnitConverter.miles_to_km(original)
        back = UnitConverter.km_to_miles(km)
        assert back == pytest.approx(original, rel=0.01)

    def test_miles_to_km_with_none(self):
        """Test None handling."""
        assert UnitConverter.miles_to_km(None) is None
        assert UnitConverter.km_to_miles(None) is None


@pytest.mark.unit
class TestFuelEconomyConversions:
    """Test fuel economy conversions (MPG/L100km)."""

    def test_mpg_to_l100km(self):
        """Test MPG to L/100km conversion."""
        # 25 MPG ≈ 9.4 L/100km
        result = UnitConverter.mpg_to_l100km(25)
        assert result == pytest.approx(9.4, rel=0.1)

    def test_l100km_to_mpg(self):
        """Test L/100km to MPG conversion."""
        # 9.4 L/100km ≈ 25 MPG
        result = UnitConverter.l100km_to_mpg(9.4)
        assert result == pytest.approx(25.0, rel=0.1)

    def test_mpg_to_l100km_roundtrip(self):
        """Test that conversion roundtrips correctly."""
        original = 30.0
        l100km = UnitConverter.mpg_to_l100km(original)
        back = UnitConverter.l100km_to_mpg(l100km)
        assert back == pytest.approx(original, rel=0.1)

    def test_mpg_to_l100km_with_zero(self):
        """Test that zero MPG returns None (division by zero)."""
        result = UnitConverter.mpg_to_l100km(0)
        assert result is None

    def test_l100km_to_mpg_with_zero(self):
        """Test that zero L/100km returns None (division by zero)."""
        result = UnitConverter.l100km_to_mpg(0)
        assert result is None

    def test_fuel_economy_with_none(self):
        """Test None handling."""
        assert UnitConverter.mpg_to_l100km(None) is None
        assert UnitConverter.l100km_to_mpg(None) is None


@pytest.mark.unit
class TestDimensionConversions:
    """Test dimension conversions (feet/meters)."""

    def test_feet_to_meters(self):
        """Test feet to meters conversion."""
        result = UnitConverter.feet_to_meters(10)
        assert result == pytest.approx(3.05, rel=0.01)

    def test_meters_to_feet(self):
        """Test meters to feet conversion."""
        result = UnitConverter.meters_to_feet(3.05)
        assert result == pytest.approx(10.0, rel=0.01)

    def test_feet_to_meters_roundtrip(self):
        """Test that conversion roundtrips correctly."""
        original = 6.0
        meters = UnitConverter.feet_to_meters(original)
        back = UnitConverter.meters_to_feet(meters)
        assert back == pytest.approx(original, rel=0.01)

    def test_feet_to_meters_with_none(self):
        """Test None handling."""
        assert UnitConverter.feet_to_meters(None) is None
        assert UnitConverter.meters_to_feet(None) is None


@pytest.mark.unit
class TestTemperatureConversions:
    """Test temperature conversions (F/C)."""

    def test_fahrenheit_to_celsius_freezing(self):
        """Test freezing point conversion."""
        result = UnitConverter.fahrenheit_to_celsius(32)
        assert result == pytest.approx(0.0, abs=0.1)

    def test_fahrenheit_to_celsius_boiling(self):
        """Test boiling point conversion."""
        result = UnitConverter.fahrenheit_to_celsius(212)
        assert result == pytest.approx(100.0, abs=0.1)

    def test_celsius_to_fahrenheit_freezing(self):
        """Test freezing point conversion."""
        result = UnitConverter.celsius_to_fahrenheit(0)
        assert result == pytest.approx(32.0, abs=0.1)

    def test_celsius_to_fahrenheit_boiling(self):
        """Test boiling point conversion."""
        result = UnitConverter.celsius_to_fahrenheit(100)
        assert result == pytest.approx(212.0, abs=0.1)

    def test_temperature_roundtrip(self):
        """Test that conversion roundtrips correctly."""
        original = 72.0
        celsius = UnitConverter.fahrenheit_to_celsius(original)
        back = UnitConverter.celsius_to_fahrenheit(celsius)
        assert back == pytest.approx(original, rel=0.01)

    def test_temperature_with_none(self):
        """Test None handling."""
        assert UnitConverter.fahrenheit_to_celsius(None) is None
        assert UnitConverter.celsius_to_fahrenheit(None) is None


@pytest.mark.unit
class TestPressureConversions:
    """Test pressure conversions (PSI/bar)."""

    def test_psi_to_bar(self):
        """Test PSI to bar conversion."""
        # 35 PSI ≈ 2.41 bar
        result = UnitConverter.psi_to_bar(35)
        assert result == pytest.approx(2.41, rel=0.01)

    def test_bar_to_psi(self):
        """Test bar to PSI conversion."""
        # 2.41 bar ≈ 35 PSI
        result = UnitConverter.bar_to_psi(2.41)
        assert result == pytest.approx(35.0, rel=0.01)

    def test_pressure_roundtrip(self):
        """Test that conversion roundtrips correctly."""
        original = 32.0
        bar = UnitConverter.psi_to_bar(original)
        back = UnitConverter.bar_to_psi(bar)
        assert back == pytest.approx(original, rel=0.01)

    def test_pressure_with_none(self):
        """Test None handling."""
        assert UnitConverter.psi_to_bar(None) is None
        assert UnitConverter.bar_to_psi(None) is None


@pytest.mark.unit
class TestWeightConversions:
    """Test weight conversions (lbs/kg)."""

    def test_lbs_to_kg(self):
        """Test pounds to kilograms conversion."""
        result = UnitConverter.lbs_to_kg(100)
        assert result == pytest.approx(45.36, rel=0.01)

    def test_kg_to_lbs(self):
        """Test kilograms to pounds conversion."""
        result = UnitConverter.kg_to_lbs(45.36)
        assert result == pytest.approx(100.0, rel=0.01)

    def test_weight_roundtrip(self):
        """Test that conversion roundtrips correctly."""
        original = 150.0
        kg = UnitConverter.lbs_to_kg(original)
        back = UnitConverter.kg_to_lbs(kg)
        assert back == pytest.approx(original, rel=0.01)

    def test_weight_with_none(self):
        """Test None handling."""
        assert UnitConverter.lbs_to_kg(None) is None
        assert UnitConverter.kg_to_lbs(None) is None


@pytest.mark.unit
class TestTorqueConversions:
    """Test torque conversions (lb-ft/Nm)."""

    def test_lbft_to_nm(self):
        """Test lb-ft to Newton-meters conversion."""
        # 100 lb-ft ≈ 135.58 Nm
        result = UnitConverter.lbft_to_nm(100)
        assert result == pytest.approx(135.58, rel=0.01)

    def test_nm_to_lbft(self):
        """Test Newton-meters to lb-ft conversion."""
        # 135.58 Nm ≈ 100 lb-ft
        result = UnitConverter.nm_to_lbft(135.58)
        assert result == pytest.approx(100.0, rel=0.01)

    def test_torque_roundtrip(self):
        """Test that conversion roundtrips correctly."""
        original = 250.0
        nm = UnitConverter.lbft_to_nm(original)
        back = UnitConverter.nm_to_lbft(nm)
        assert back == pytest.approx(original, rel=0.01)

    def test_torque_with_none(self):
        """Test None handling."""
        assert UnitConverter.lbft_to_nm(None) is None
        assert UnitConverter.nm_to_lbft(None) is None


@pytest.mark.unit
class TestDecimalPrecision:
    """Test that Decimal precision is maintained."""

    def test_decimal_input_precision(self):
        """Test that Decimal inputs maintain precision."""
        value = Decimal("10.123456789")
        result = UnitConverter.gallons_to_liters(value)
        # Result should be rounded to 2 decimal places
        assert isinstance(result, float)
        # But the calculation should use full precision internally
        expected = float(value * Decimal("3.78541"))
        assert result == pytest.approx(expected, rel=0.001)

    def test_float_input_precision(self):
        """Test that float inputs are converted properly."""
        result = UnitConverter.miles_to_km(100.5)
        assert isinstance(result, float)
        assert result == pytest.approx(161.74, rel=0.01)

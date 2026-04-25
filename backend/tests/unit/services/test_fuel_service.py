"""
Unit tests for fuel service L/100km calculations.

Tests fuel economy calculations, partial fill-up handling, and hauling adjustments.
Metric-canonical since v2.26.2: liters / odometer_km / L/100km (lower is better).
"""

from datetime import date
from decimal import Decimal

import pytest

from app.models.fuel import FuelRecord
from app.services.fuel_service import calculate_l_per_100km


@pytest.mark.unit
@pytest.mark.fuel
class TestMPGCalculation:
    """Test L/100km calculation logic."""

    def test_calculate_mpg_full_tank(self):
        """Test L/100km calculation for a full tank fill-up."""
        # Previous record: 16093.4 km
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            odometer_km=Decimal("16093.40"),
            liters=Decimal("45.42"),
            is_full_tank=True,
        )

        # Current record: distance 482.80 km, 45.42 liters
        # 45.42 L / (482.80 km / 100) = 9.41 L/100km
        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            odometer_km=Decimal("16576.20"),
            liters=Decimal("45.42"),
            is_full_tank=True,
        )

        result = calculate_l_per_100km(current_record, previous_record)

        assert result == Decimal("9.41")

    def test_calculate_mpg_partial_fillup_returns_none(self):
        """Test that partial fill-ups don't calculate L/100km."""
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            odometer_km=Decimal("16093.40"),
            liters=Decimal("45.42"),
            is_full_tank=True,
        )

        # Current record is partial fill-up
        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            odometer_km=Decimal("16576.20"),
            liters=Decimal("30.28"),
            is_full_tank=False,  # Partial fill-up
        )

        result = calculate_l_per_100km(current_record, previous_record)

        assert result is None

    def test_calculate_mpg_no_previous_record(self):
        """Test that L/100km can't be calculated without previous record."""
        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            odometer_km=Decimal("16576.20"),
            liters=Decimal("45.42"),
            is_full_tank=True,
        )

        result = calculate_l_per_100km(current_record, None)

        assert result is None

    def test_calculate_mpg_no_mileage_on_current(self):
        """Test that L/100km can't be calculated without current odometer."""
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            odometer_km=Decimal("16093.40"),
            liters=Decimal("45.42"),
            is_full_tank=True,
        )

        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            odometer_km=None,  # No odometer
            liters=Decimal("45.42"),
            is_full_tank=True,
        )

        result = calculate_l_per_100km(current_record, previous_record)

        assert result is None

    def test_calculate_mpg_no_mileage_on_previous(self):
        """Test that L/100km can't be calculated without previous odometer."""
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            odometer_km=None,  # No odometer
            liters=Decimal("45.42"),
            is_full_tank=True,
        )

        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            odometer_km=Decimal("16576.20"),
            liters=Decimal("45.42"),
            is_full_tank=True,
        )

        result = calculate_l_per_100km(current_record, previous_record)

        assert result is None

    def test_calculate_mpg_no_gallons(self):
        """Test that L/100km can't be calculated without liters."""
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            odometer_km=Decimal("16093.40"),
            liters=Decimal("45.42"),
            is_full_tank=True,
        )

        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            odometer_km=Decimal("16576.20"),
            liters=None,  # No liters
            is_full_tank=True,
        )

        result = calculate_l_per_100km(current_record, previous_record)

        assert result is None

    def test_calculate_mpg_negative_distance(self):
        """Test that negative distances (odometer rollback) return None."""
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            odometer_km=Decimal("16576.20"),
            liters=Decimal("45.42"),
            is_full_tank=True,
        )

        # Current odometer is LESS than previous (rollback)
        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            odometer_km=Decimal("16093.40"),
            liters=Decimal("45.42"),
            is_full_tank=True,
        )

        result = calculate_l_per_100km(current_record, previous_record)

        assert result is None

    def test_calculate_mpg_zero_distance(self):
        """Test that zero distance (same odometer) returns None."""
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            odometer_km=Decimal("16093.40"),
            liters=Decimal("45.42"),
            is_full_tank=True,
        )

        # Current odometer is same as previous
        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            odometer_km=Decimal("16093.40"),
            liters=Decimal("45.42"),
            is_full_tank=True,
        )

        result = calculate_l_per_100km(current_record, previous_record)

        assert result is None

    def test_calculate_mpg_zero_gallons(self):
        """Test that zero liters returns None."""
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            odometer_km=Decimal("16093.40"),
            liters=Decimal("45.42"),
            is_full_tank=True,
        )

        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            odometer_km=Decimal("16576.20"),
            liters=Decimal("0.0"),  # Zero liters
            is_full_tank=True,
        )

        result = calculate_l_per_100km(current_record, previous_record)

        assert result is None

    def test_calculate_mpg_rounding(self):
        """Test that L/100km is rounded to 2 decimal places."""
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            odometer_km=Decimal("16093.40"),
            liters=Decimal("45.42"),
            is_full_tank=True,
        )

        # 535.92 km / 45.42 L = 11.79 km/L → 8.48 L/100km
        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            odometer_km=Decimal("16629.32"),
            liters=Decimal("45.42"),
            is_full_tank=True,
        )

        result = calculate_l_per_100km(current_record, previous_record)

        # 45.42 / 535.92 * 100 = 8.475 → rounds to 8.48
        assert result == Decimal("8.48")
        # Check it's actually rounded to 2 places
        assert result.as_tuple().exponent == -2

    def test_calculate_mpg_high_efficiency(self):
        """Test L/100km calculation for high-efficiency vehicle."""
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            odometer_km=Decimal("16093.40"),
            liters=Decimal("37.85"),
            is_full_tank=True,
        )

        # 804.67 km / 37.85 L → 4.70 L/100km (hybrid/efficient)
        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            odometer_km=Decimal("16898.07"),
            liters=Decimal("37.85"),
            is_full_tank=True,
        )

        result = calculate_l_per_100km(current_record, previous_record)

        # 37.85 / 804.67 * 100 = 4.7038... → 4.70
        assert result == Decimal("4.70")

    def test_calculate_mpg_low_efficiency(self):
        """Test L/100km calculation for low-efficiency vehicle."""
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            odometer_km=Decimal("16093.40"),
            liters=Decimal("75.71"),
            is_full_tank=True,
        )

        # 321.87 km / 75.71 L → 23.52 L/100km (truck/SUV)
        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            odometer_km=Decimal("16415.27"),
            liters=Decimal("75.71"),
            is_full_tank=True,
        )

        result = calculate_l_per_100km(current_record, previous_record)

        # 75.71 / 321.87 * 100 = 23.522... → 23.52
        assert result == Decimal("23.52")

    def test_calculate_mpg_small_tank(self):
        """Test L/100km calculation with small tank (motorcycle/small car)."""
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            odometer_km=Decimal("8046.70"),
            liters=Decimal("13.25"),
            is_full_tank=True,
        )

        # 241.40 km / 13.25 L → 5.49 L/100km
        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            odometer_km=Decimal("8288.10"),
            liters=Decimal("13.25"),
            is_full_tank=True,
        )

        result = calculate_l_per_100km(current_record, previous_record)

        # 13.25 / 241.40 * 100 = 5.4888... → 5.49
        assert result == Decimal("5.49")

    def test_calculate_mpg_decimal_precision(self):
        """Test that L/100km calculation handles Decimal types correctly."""
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            odometer_km=Decimal("16093.40"),
            liters=Decimal("46.737"),  # Precise decimal
            is_full_tank=True,
        )

        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            odometer_km=Decimal("16576.20"),
            liters=Decimal("46.737"),
            is_full_tank=True,
        )

        result = calculate_l_per_100km(current_record, previous_record)

        assert isinstance(result, Decimal)
        # 46.737 / 482.80 * 100 = 9.6804... → 9.68
        assert result == Decimal("9.68")


@pytest.mark.unit
@pytest.mark.fuel
class TestCostCalculations:
    """Test fuel cost-related calculations."""

    def test_cost_per_mile_calculation(self):
        """Test calculating cost per kilometer driven."""
        # 482.80 km, $45.00 cost = ~$0.0932 per km
        km = Decimal("482.80")
        cost = Decimal("45.00")

        cost_per_km = cost / km

        # Sanity check on division
        assert round(cost_per_km, 4) == Decimal("0.0932")

    def test_cost_per_gallon_calculation(self):
        """Test calculating cost per liter."""
        # $45.00 for 45.42 liters = ~$0.99/L
        cost = Decimal("45.00")
        liters = Decimal("45.42")

        cost_per_liter = cost / liters

        assert round(cost_per_liter, 2) == Decimal("0.99")

    def test_total_cost_calculation(self):
        """Test calculating total cost from liters and price."""
        liters = Decimal("47.32")
        price_per_liter = Decimal("0.962")

        total_cost = liters * price_per_liter

        # 47.32 * 0.962 = 45.52184
        assert round(total_cost, 2) == Decimal("45.52")

"""
Unit tests for fuel service MPG calculations.

Tests fuel economy calculations, partial fill-up handling, and hauling adjustments.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.models.fuel import FuelRecord
from app.services.fuel_service import calculate_mpg


@pytest.mark.unit
@pytest.mark.fuel
class TestMPGCalculation:
    """Test MPG calculation logic."""

    def test_calculate_mpg_full_tank(self):
        """Test MPG calculation for a full tank fill-up."""
        # Previous record: 10,000 miles
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            mileage=10000,
            gallons=Decimal("12.0"),
            is_full_tank=True,
        )

        # Current record: 10,300 miles, 12 gallons
        # 300 miles / 12 gallons = 25 MPG
        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            mileage=10300,
            gallons=Decimal("12.0"),
            is_full_tank=True,
        )

        mpg = calculate_mpg(current_record, previous_record)

        assert mpg == Decimal("25.00")

    def test_calculate_mpg_partial_fillup_returns_none(self):
        """Test that partial fill-ups don't calculate MPG."""
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            mileage=10000,
            gallons=Decimal("12.0"),
            is_full_tank=True,
        )

        # Current record is partial fill-up
        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            mileage=10300,
            gallons=Decimal("8.0"),
            is_full_tank=False,  # Partial fill-up
        )

        mpg = calculate_mpg(current_record, previous_record)

        assert mpg is None

    def test_calculate_mpg_no_previous_record(self):
        """Test that MPG can't be calculated without previous record."""
        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            mileage=10300,
            gallons=Decimal("12.0"),
            is_full_tank=True,
        )

        mpg = calculate_mpg(current_record, None)

        assert mpg is None

    def test_calculate_mpg_no_mileage_on_current(self):
        """Test that MPG can't be calculated without current mileage."""
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            mileage=10000,
            gallons=Decimal("12.0"),
            is_full_tank=True,
        )

        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            mileage=None,  # No mileage
            gallons=Decimal("12.0"),
            is_full_tank=True,
        )

        mpg = calculate_mpg(current_record, previous_record)

        assert mpg is None

    def test_calculate_mpg_no_mileage_on_previous(self):
        """Test that MPG can't be calculated without previous mileage."""
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            mileage=None,  # No mileage
            gallons=Decimal("12.0"),
            is_full_tank=True,
        )

        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            mileage=10300,
            gallons=Decimal("12.0"),
            is_full_tank=True,
        )

        mpg = calculate_mpg(current_record, previous_record)

        assert mpg is None

    def test_calculate_mpg_no_gallons(self):
        """Test that MPG can't be calculated without gallons."""
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            mileage=10000,
            gallons=Decimal("12.0"),
            is_full_tank=True,
        )

        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            mileage=10300,
            gallons=None,  # No gallons
            is_full_tank=True,
        )

        mpg = calculate_mpg(current_record, previous_record)

        assert mpg is None

    def test_calculate_mpg_negative_distance(self):
        """Test that negative distances (odometer rollback) return None."""
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            mileage=10300,
            gallons=Decimal("12.0"),
            is_full_tank=True,
        )

        # Current mileage is LESS than previous (rollback)
        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            mileage=10000,
            gallons=Decimal("12.0"),
            is_full_tank=True,
        )

        mpg = calculate_mpg(current_record, previous_record)

        assert mpg is None

    def test_calculate_mpg_zero_distance(self):
        """Test that zero distance (same odometer) returns None."""
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            mileage=10000,
            gallons=Decimal("12.0"),
            is_full_tank=True,
        )

        # Current mileage is same as previous
        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            mileage=10000,
            gallons=Decimal("12.0"),
            is_full_tank=True,
        )

        mpg = calculate_mpg(current_record, previous_record)

        assert mpg is None

    def test_calculate_mpg_zero_gallons(self):
        """Test that zero gallons returns None."""
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            mileage=10000,
            gallons=Decimal("12.0"),
            is_full_tank=True,
        )

        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            mileage=10300,
            gallons=Decimal("0.0"),  # Zero gallons
            is_full_tank=True,
        )

        mpg = calculate_mpg(current_record, previous_record)

        assert mpg is None

    def test_calculate_mpg_rounding(self):
        """Test that MPG is rounded to 2 decimal places."""
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            mileage=10000,
            gallons=Decimal("12.0"),
            is_full_tank=True,
        )

        # 333 miles / 12 gallons = 27.75 MPG
        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            mileage=10333,
            gallons=Decimal("12.0"),
            is_full_tank=True,
        )

        mpg = calculate_mpg(current_record, previous_record)

        assert mpg == Decimal("27.75")
        # Check it's actually rounded to 2 places
        assert mpg.as_tuple().exponent == -2

    def test_calculate_mpg_high_efficiency(self):
        """Test MPG calculation for high-efficiency vehicle."""
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            mileage=10000,
            gallons=Decimal("10.0"),
            is_full_tank=True,
        )

        # 500 miles / 10 gallons = 50 MPG (hybrid/efficient car)
        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            mileage=10500,
            gallons=Decimal("10.0"),
            is_full_tank=True,
        )

        mpg = calculate_mpg(current_record, previous_record)

        assert mpg == Decimal("50.00")

    def test_calculate_mpg_low_efficiency(self):
        """Test MPG calculation for low-efficiency vehicle."""
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            mileage=10000,
            gallons=Decimal("20.0"),
            is_full_tank=True,
        )

        # 200 miles / 20 gallons = 10 MPG (truck/SUV)
        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            mileage=10200,
            gallons=Decimal("20.0"),
            is_full_tank=True,
        )

        mpg = calculate_mpg(current_record, previous_record)

        assert mpg == Decimal("10.00")

    def test_calculate_mpg_small_tank(self):
        """Test MPG calculation with small tank (motorcycle/small car)."""
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            mileage=5000,
            gallons=Decimal("3.5"),
            is_full_tank=True,
        )

        # 150 miles / 3.5 gallons = 42.86 MPG
        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            mileage=5150,
            gallons=Decimal("3.5"),
            is_full_tank=True,
        )

        mpg = calculate_mpg(current_record, previous_record)

        assert mpg == Decimal("42.86")

    def test_calculate_mpg_decimal_precision(self):
        """Test that MPG calculation handles Decimal types correctly."""
        previous_record = FuelRecord(
            id="prev-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 1),
            mileage=10000,
            gallons=Decimal("12.345"),  # Precise decimal
            is_full_tank=True,
        )

        current_record = FuelRecord(
            id="curr-1",
            vin="1HGBH41JXMN109186",
            date=date(2024, 1, 15),
            mileage=10300,
            gallons=Decimal("12.345"),
            is_full_tank=True,
        )

        mpg = calculate_mpg(current_record, previous_record)

        assert isinstance(mpg, Decimal)
        assert mpg == Decimal("24.30")  # 300 / 12.345 = 24.30


@pytest.mark.unit
@pytest.mark.fuel
class TestCostCalculations:
    """Test fuel cost-related calculations."""

    def test_cost_per_mile_calculation(self):
        """Test calculating cost per mile driven."""
        # 300 miles, $45.00 cost = $0.15 per mile
        miles = 300
        cost = Decimal("45.00")

        cost_per_mile = cost / miles

        assert cost_per_mile == Decimal("0.15")

    def test_cost_per_gallon_calculation(self):
        """Test calculating cost per gallon."""
        # $45.00 for 12 gallons = $3.75/gallon
        cost = Decimal("45.00")
        gallons = Decimal("12.0")

        cost_per_gallon = cost / gallons

        assert cost_per_gallon == Decimal("3.75")

    def test_total_cost_calculation(self):
        """Test calculating total cost from gallons and price."""
        gallons = Decimal("12.5")
        price_per_gallon = Decimal("3.64")

        total_cost = gallons * price_per_gallon

        assert total_cost == Decimal("45.50")

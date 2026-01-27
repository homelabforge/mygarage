"""
Integration test fixtures and configuration.

Integration tests use the database and test full request/response cycles.
These fixtures extend the base conftest.py fixtures.
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest


@pytest.fixture
async def test_vehicle_with_records(test_vehicle, db_session):
    """
    Create a test vehicle with sample fuel and service records.

    This fixture provides a fully populated vehicle for integration testing.
    """
    from app.models.fuel import FuelRecord
    from app.models.service import ServiceRecord

    # Add fuel records
    fuel_records = [
        FuelRecord(
            vin=test_vehicle["vin"],
            date=(datetime.now() - timedelta(days=30)).date(),
            mileage=14000,
            gallons=Decimal("12.0"),
            cost=Decimal("42.00"),
            price_per_unit=Decimal("3.50"),
            fuel_type="Regular",
            is_full_tank=True,
            missed_fillup=False,
        ),
        FuelRecord(
            vin=test_vehicle["vin"],
            date=(datetime.now() - timedelta(days=15)).date(),
            mileage=14366,
            gallons=Decimal("11.5"),
            cost=Decimal("40.25"),
            price_per_unit=Decimal("3.50"),
            fuel_type="Regular",
            is_full_tank=True,
            missed_fillup=False,
        ),
        FuelRecord(
            vin=test_vehicle["vin"],
            date=datetime.now().date(),
            mileage=15000,
            gallons=Decimal("12.5"),
            cost=Decimal("45.50"),
            price_per_unit=Decimal("3.64"),
            fuel_type="Regular",
            is_full_tank=True,
            missed_fillup=False,
        ),
    ]

    # Add service records
    service_records = [
        ServiceRecord(
            vin=test_vehicle["vin"],
            service_type="Oil Change",
            service_category="Maintenance",
            date=(datetime.now() - timedelta(days=90)).date(),
            mileage=12000,
            cost=Decimal("45.99"),
            vendor_name="Jiffy Lube",
            notes="5W-30 synthetic oil",
        ),
        ServiceRecord(
            vin=test_vehicle["vin"],
            service_type="Tire Rotation",
            service_category="Maintenance",
            date=(datetime.now() - timedelta(days=45)).date(),
            mileage=13500,
            cost=Decimal("25.00"),
            vendor_name="Discount Tire",
            notes="Rotated and balanced",
        ),
    ]

    for record in fuel_records:
        db_session.add(record)
    for record in service_records:
        db_session.add(record)

    await db_session.commit()

    # Return vehicle data directly accessible plus the records
    # Spread test_vehicle dict so vin, year, etc. are directly accessible
    return {
        **test_vehicle,
        "fuel_records": fuel_records,
        "service_records": service_records,
    }


@pytest.fixture
def sample_service_payload():
    """Sample payload for creating a service record."""
    return {
        "service_type": "Oil Change",
        "service_category": "Maintenance",
        "date": datetime.now().date().isoformat(),
        "mileage": 15000,
        "cost": 45.99,
        "vendor_name": "Test Garage",
        "notes": "Test service record",
    }


@pytest.fixture
def sample_fuel_payload():
    """Sample payload for creating a fuel record."""
    return {
        "date": datetime.now().date().isoformat(),
        "mileage": 15000,
        "gallons": 12.5,
        "cost": 45.50,
        "price_per_unit": 3.64,
        "fuel_type": "Regular",
        "is_full_tank": True,
        "missed_fillup": False,
        "is_hauling": False,
    }


@pytest.fixture
def sample_vehicle_payload():
    """Sample payload for creating a vehicle."""
    return {
        "vin": "1HGCM82633A123456",
        "nickname": "Test Accord",  # Required field
        "vehicle_type": "Car",  # Required field
        "year": 2023,
        "make": "Honda",
        "model": "Accord",
        "trim": "EX-L",
        "license_plate": "TEST-123",
    }

"""
Integration test fixtures and configuration.

Integration tests use the database and test full request/response cycles.
These fixtures extend the base conftest.py fixtures.
"""

import pytest
from datetime import datetime, timedelta
from decimal import Decimal


@pytest.fixture
async def test_vehicle_with_records(test_vehicle, db_session):
    """
    Create a test vehicle with sample fuel and service records.

    This fixture provides a fully populated vehicle for integration testing.
    """
    from app.models.fuel import FuelRecord
    from app.models.service import ServiceRecord

    vehicle_id = test_vehicle["id"]

    # Add fuel records
    fuel_records = [
        FuelRecord(
            vehicle_id=vehicle_id,
            date=(datetime.now() - timedelta(days=30)).date(),
            odometer=14000,
            gallons=Decimal("12.0"),
            cost=Decimal("42.00"),
            cost_per_gallon=Decimal("3.50"),
            station="Shell",
            partial_fillup=False,
            mpg=Decimal("30.5"),
        ),
        FuelRecord(
            vehicle_id=vehicle_id,
            date=(datetime.now() - timedelta(days=15)).date(),
            odometer=14366,
            gallons=Decimal("11.5"),
            cost=Decimal("40.25"),
            cost_per_gallon=Decimal("3.50"),
            station="Mobil",
            partial_fillup=False,
            mpg=Decimal("31.8"),
        ),
        FuelRecord(
            vehicle_id=vehicle_id,
            date=datetime.now().date(),
            odometer=15000,
            gallons=Decimal("12.5"),
            cost=Decimal("45.50"),
            cost_per_gallon=Decimal("3.64"),
            station="BP",
            partial_fillup=False,
            mpg=Decimal("28.5"),
        ),
    ]

    # Add service records
    service_records = [
        ServiceRecord(
            vehicle_id=vehicle_id,
            service_type="oil_change",
            date=(datetime.now() - timedelta(days=90)).date(),
            odometer=12000,
            cost=Decimal("45.99"),
            vendor="Jiffy Lube",
            notes="5W-30 synthetic oil",
        ),
        ServiceRecord(
            vehicle_id=vehicle_id,
            service_type="tire_rotation",
            date=(datetime.now() - timedelta(days=45)).date(),
            odometer=13500,
            cost=Decimal("25.00"),
            vendor="Discount Tire",
            notes="Rotated and balanced",
        ),
    ]

    for record in fuel_records:
        db_session.add(record)
    for record in service_records:
        db_session.add(record)

    await db_session.commit()

    return {
        "vehicle": test_vehicle,
        "fuel_records": fuel_records,
        "service_records": service_records,
    }


@pytest.fixture
def sample_service_payload():
    """Sample payload for creating a service record."""
    return {
        "service_type": "oil_change",
        "date": datetime.now().date().isoformat(),
        "odometer": 15000,
        "cost": 45.99,
        "vendor": "Test Garage",
        "notes": "Test service record",
        "next_due_mileage": 18000,
        "next_due_date": (datetime.now() + timedelta(days=90)).date().isoformat(),
    }


@pytest.fixture
def sample_fuel_payload():
    """Sample payload for creating a fuel record."""
    return {
        "date": datetime.now().date().isoformat(),
        "odometer": 15000,
        "gallons": 12.5,
        "cost": 45.50,
        "cost_per_gallon": 3.64,
        "station": "Test Station",
        "partial_fillup": False,
        "hauling": False,
    }


@pytest.fixture
def sample_vehicle_payload():
    """Sample payload for creating a vehicle."""
    return {
        "vin": "1HGCM82633A123456",
        "year": 2023,
        "make": "Honda",
        "model": "Accord",
        "trim": "EX-L",
        "license_plate": "TEST-123",
        "current_odometer": 15000,
    }

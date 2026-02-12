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
    Create a test vehicle with sample fuel records and service visits.

    This fixture provides a fully populated vehicle for integration testing.
    """
    # Create or get vendors
    from sqlalchemy import select

    from app.models.fuel import FuelRecord
    from app.models.service_line_item import ServiceLineItem
    from app.models.service_visit import ServiceVisit
    from app.models.vendor import Vendor

    jiffy_result = await db_session.execute(
        select(Vendor).where(Vendor.name == "Jiffy Lube").limit(1)
    )
    jiffy_vendor = jiffy_result.scalar_one_or_none()
    if not jiffy_vendor:
        jiffy_vendor = Vendor(name="Jiffy Lube")
        db_session.add(jiffy_vendor)

    discount_result = await db_session.execute(
        select(Vendor).where(Vendor.name == "Discount Tire").limit(1)
    )
    discount_vendor = discount_result.scalar_one_or_none()
    if not discount_vendor:
        discount_vendor = Vendor(name="Discount Tire")
        db_session.add(discount_vendor)

    await db_session.flush()

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

    # Add service visits with line items
    visit1 = ServiceVisit(
        vin=test_vehicle["vin"],
        vendor_id=jiffy_vendor.id,
        service_category="Maintenance",
        date=(datetime.now() - timedelta(days=90)).date(),
        mileage=12000,
        total_cost=Decimal("45.99"),
        notes="5W-30 synthetic oil",
    )
    visit2 = ServiceVisit(
        vin=test_vehicle["vin"],
        vendor_id=discount_vendor.id,
        service_category="Maintenance",
        date=(datetime.now() - timedelta(days=45)).date(),
        mileage=13500,
        total_cost=Decimal("25.00"),
        notes="Rotated and balanced",
    )

    for record in fuel_records:
        db_session.add(record)
    db_session.add(visit1)
    db_session.add(visit2)
    await db_session.flush()

    # Add line items
    line1 = ServiceLineItem(
        visit_id=visit1.id,
        description="Oil Change",
        cost=Decimal("45.99"),
    )
    line2 = ServiceLineItem(
        visit_id=visit2.id,
        description="Tire Rotation",
        cost=Decimal("25.00"),
    )
    db_session.add(line1)
    db_session.add(line2)

    await db_session.commit()

    return {
        **test_vehicle,
        "fuel_records": fuel_records,
        "service_visits": [visit1, visit2],
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
def sample_def_payload():
    """Sample payload for creating a DEF record."""
    return {
        "date": datetime.now().date().isoformat(),
        "mileage": 16000,
        "gallons": 2.5,
        "cost": 18.75,
        "price_per_unit": 7.50,
        "fill_level": 0.85,
        "source": "Truck Stop",
        "brand": "BlueDEF",
        "notes": "Test DEF fill",
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

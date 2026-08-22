"""
Integration test fixtures and configuration.

Integration tests use the database and test full request/response cycles.
These fixtures extend the base conftest.py fixtures.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

# Seed dates for `test_vehicle_with_records` are FIXED, never relative to today.
#
# The test database is session-scoped and `db_session` does not roll back, so
# every row this fixture commits stays visible to every later test in the run —
# including tests that only asked for the bare `test_vehicle` fixture, which
# shares the same VIN. A seed date computed as `datetime.now() - timedelta(...)`
# therefore sweeps forward one day at a time until it lands on a date some other
# test hardcodes for that VIN, at which point that test's `scalar_one()` raises
# MultipleResultsFound. That is exactly what broke the v3.0.0 publish run: the
# 90-day-old service visit became 2026-05-17 on 2026-08-15 and collided with
# test_import_data.py's engine-hours import test.
#
# This anchor sits in a band the suite never uses — the date literals in tests
# cluster in 2024-01..09, 2025-01/03/06/07/12 and 2026-01..05 — and being fixed,
# it cannot drift into one later. Keep the offsets below relative to the anchor
# so the spacing between records stays meaningful; if you add a seed row here,
# pick another date in the same clear band.
_SEED_ANCHOR = date(2023, 7, 15)


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
            date=_SEED_ANCHOR - timedelta(days=30),
            odometer_km=Decimal("22530.76"),  # 14000 mi
            liters=Decimal("45.425"),  # 12.0 gal
            cost=Decimal("42.00"),
            price_per_unit=Decimal("3.50"),
            fuel_type_used="gasoline",
            is_full_tank=True,
            missed_fillup=False,
        ),
        FuelRecord(
            vin=test_vehicle["vin"],
            date=_SEED_ANCHOR - timedelta(days=15),
            odometer_km=Decimal("23119.55"),  # 14366 mi
            liters=Decimal("43.532"),  # 11.5 gal
            cost=Decimal("40.25"),
            price_per_unit=Decimal("3.50"),
            fuel_type_used="gasoline",
            is_full_tank=True,
            missed_fillup=False,
        ),
        FuelRecord(
            vin=test_vehicle["vin"],
            date=_SEED_ANCHOR,
            odometer_km=Decimal("24140.10"),  # 15000 mi
            liters=Decimal("47.318"),  # 12.5 gal
            cost=Decimal("45.50"),
            price_per_unit=Decimal("3.64"),
            fuel_type_used="gasoline",
            is_full_tank=True,
            missed_fillup=False,
        ),
    ]

    # Add service visits with line items
    visit1 = ServiceVisit(
        vin=test_vehicle["vin"],
        vendor_id=jiffy_vendor.id,
        service_category="Maintenance",
        date=_SEED_ANCHOR - timedelta(days=90),
        odometer_km=Decimal("19312.08"),  # 12000 mi
        total_cost=Decimal("45.99"),
        notes="5W-30 synthetic oil",
    )
    visit2 = ServiceVisit(
        vin=test_vehicle["vin"],
        vendor_id=discount_vendor.id,
        service_category="Maintenance",
        date=_SEED_ANCHOR - timedelta(days=45),
        odometer_km=Decimal("21726.09"),  # 13500 mi
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
        "odometer_km": 24140.10,  # 15000 mi
        "cost": 45.99,
        "vendor_name": "Test Garage",
        "notes": "Test service record",
    }


@pytest.fixture
def sample_fuel_payload():
    """Sample payload for creating a fuel record."""
    return {
        "date": datetime.now().date().isoformat(),
        "odometer_km": 24140.10,  # 15000 mi
        "liters": 47.318,  # 12.5 gal
        "cost": 45.50,
        "price_per_unit": 3.64,
        "fuel_type_used": "gasoline",
        "is_full_tank": True,
        "missed_fillup": False,
        "is_hauling": False,
    }


@pytest.fixture
def sample_def_payload():
    """Sample payload for creating a DEF record."""
    return {
        "date": datetime.now().date().isoformat(),
        "odometer_km": 25749.44,  # 16000 mi
        "liters": 9.464,  # 2.5 gal
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

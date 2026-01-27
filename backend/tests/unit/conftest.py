"""
Unit test fixtures and configuration.

Unit tests should not require database access and test pure functions/logic.
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest


@pytest.fixture
def mock_vehicle_data():
    """Mock vehicle data for unit tests."""
    return {
        "id": "test-vehicle-123",
        "user_id": "test-user-456",
        "vin": "1HGCM82633A123456",
        "year": 2023,
        "make": "Honda",
        "model": "Accord",
        "trim": "EX-L",
        "license_plate": "ABC-1234",
        "current_odometer": 15000,
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }


@pytest.fixture
def mock_fuel_record_data():
    """Mock fuel record data for unit tests."""
    return {
        "id": "fuel-123",
        "vehicle_id": "test-vehicle-123",
        "date": datetime.now().date(),
        "odometer": 15000,
        "gallons": Decimal("12.5"),
        "cost": Decimal("45.50"),
        "cost_per_gallon": Decimal("3.64"),
        "station": "Shell",
        "partial_fillup": False,
        "hauling": False,
        "mpg": Decimal("28.5"),
    }


@pytest.fixture
def mock_service_record_data():
    """Mock service record data for unit tests."""
    return {
        "id": "service-123",
        "vehicle_id": "test-vehicle-123",
        "service_type": "oil_change",
        "date": datetime.now().date(),
        "odometer": 15000,
        "cost": Decimal("45.99"),
        "vendor": "Jiffy Lube",
        "notes": "5W-30 synthetic oil",
        "next_due_mileage": 18000,
        "next_due_date": (datetime.now() + timedelta(days=90)).date(),
    }


@pytest.fixture
def mock_user_data():
    """Mock user data for unit tests."""
    return {
        "id": "test-user-456",
        "email": "test@example.com",
        "username": "testuser",
        "is_active": True,
        "is_superuser": False,
        "created_at": datetime.now(),
    }

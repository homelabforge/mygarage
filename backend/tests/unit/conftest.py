"""
Unit test fixtures and configuration.

Unit tests should not require database access and test pure functions/logic.
Some subdirectories (utils, services) do exercise db_session for sync/derive
helpers that are thin wrappers over a single query — those tests still live
under unit/ by existing convention (see test_odometer_sync.py, test_def_sync.py).
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import HoursRecord


@pytest_asyncio.fixture
async def clean_hours_records(db_session: AsyncSession, test_vehicle):
    """Clean up hours_records for the shared test vehicle before/after each test.

    Shared by ``tests/unit/utils/test_hours_sync.py`` and
    ``tests/unit/services/test_hours_service.py``. Scoped to ONLY
    ``hours_records`` — the shared ``test_vehicle`` vin is reused across many
    test files (fuel/service sync tests among them), and a blanket
    vin-scoped delete on ``fuel_records``/``service_visits`` broke
    ``test_odometer_sync.py`` (which relies on FuelRecord rows with specific
    low ids created earlier in the full suite run) when that was tried.
    Parent fuel/service rows created by hours tests are cleaned up
    individually, by id, in their own fixtures.
    """
    await db_session.execute(delete(HoursRecord).where(HoursRecord.vin == test_vehicle["vin"]))
    await db_session.commit()
    yield
    await db_session.execute(delete(HoursRecord).where(HoursRecord.vin == test_vehicle["vin"]))
    await db_session.commit()


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

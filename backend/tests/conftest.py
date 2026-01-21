"""Pytest configuration and fixtures for MyGarage backend tests."""

import os

# Enable test mode BEFORE importing app (disables CSRF validation in middleware)
os.environ["MYGARAGE_TEST_MODE"] = "true"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select
from typing import AsyncGenerator, NoReturn

from app.main import app
from app.database import get_db, Base
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.service import ServiceRecord
from app.models.fuel import FuelRecord


def skip_test(reason: str) -> NoReturn:
    """Skip test with given reason - typed to indicate it never returns."""
    pytest.skip(reason)
    raise AssertionError("pytest.skip should have raised")


# Test database URL - defaults to SQLite for isolated testing
# Override with TEST_DATABASE_URL environment variable if needed
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "sqlite+aiosqlite:///./test_mygarage.db"
)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_engine():
    """Create async engine for tests."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_sessionmaker(test_engine):
    """Create session maker for tests."""
    return async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def init_test_db(test_engine):
    """Initialize test database schema."""
    async with test_engine.begin() as conn:
        # Create all tables from SQLAlchemy models
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Cleanup after tests
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session(test_sessionmaker, init_test_db) -> AsyncGenerator[AsyncSession, None]:
    """Provide a database session for tests. Depends on init_test_db to ensure tables exist."""
    async with test_sessionmaker() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session) -> AsyncGenerator[AsyncClient, None]:
    """Provide an async HTTP client for testing API endpoints."""

    # Override the get_db dependency to use our test session
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    # Clean up overrides
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> dict[str, object]:
    """Create or get a test user. Returns dict for easy test access.

    Always resets the user to active state to ensure test isolation.
    Queries by username to match uniqueness constraint.
    """
    from sqlalchemy import or_

    # Pre-computed hash for "testpassword123" using argon2id with same settings as auth.py
    # This avoids calling hash_password() which requires threads (fails in PID-limited containers)
    TEST_PASSWORD_HASH = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"

    # Try to get existing test user (check both username and email for conflicts)
    result = await db_session.execute(
        select(User).where(
            or_(
                User.username == "testuser",
                User.email == "testuser@example.com"
            )
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        # Create test user
        user = User(
            username="testuser",
            email="testuser@example.com",
            hashed_password=TEST_PASSWORD_HASH,
            is_active=True,
            is_admin=True,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
    else:
        # Reset user to known good state for test isolation
        # Also ensure username and email match expected values
        user.username = "testuser"
        user.email = "testuser@example.com"
        user.is_active = True
        user.is_admin = True
        await db_session.commit()
        await db_session.refresh(user)

    # Return as dict for easier test access
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_active": user.is_active,
        "is_admin": user.is_admin,
    }


@pytest_asyncio.fixture
async def test_vehicle(db_session: AsyncSession, test_user: dict[str, object]) -> dict[str, object]:
    """Create or get a test vehicle. Returns dict for easy test access."""
    user_id = test_user["id"]
    test_vin = "1HGBH41JXMN109186"

    # Try to get the specific test vehicle by VIN
    result = await db_session.execute(
        select(Vehicle).where(Vehicle.vin == test_vin)
    )
    vehicle = result.scalar_one_or_none()

    if not vehicle:
        # Create test vehicle
        vehicle = Vehicle(
            vin=test_vin,
            user_id=user_id,
            nickname="Test Vehicle",
            vehicle_type="Car",
            year=2018,
            make="Honda",
            model="Accord",
        )
        db_session.add(vehicle)
        await db_session.commit()
        await db_session.refresh(vehicle)

    # Return as dict for easier test access (consistent with test_user fixture)
    return {
        "vin": vehicle.vin,
        "user_id": vehicle.user_id,
        "nickname": vehicle.nickname,
        "vehicle_type": vehicle.vehicle_type,
        "year": vehicle.year,
        "make": vehicle.make,
        "model": vehicle.model,
    }


@pytest_asyncio.fixture
async def vehicle_with_service_records(
    db_session: AsyncSession, test_user: dict[str, object]
) -> Vehicle:
    """Get a vehicle that has service records."""
    user_id = test_user["id"]
    # Find a vehicle with service records
    result = await db_session.execute(
        select(Vehicle).where(Vehicle.user_id == user_id).limit(10)
    )
    vehicles = result.scalars().all()

    for vehicle in vehicles:
        service_result = await db_session.execute(
            select(ServiceRecord).where(ServiceRecord.vin == vehicle.vin).limit(1)
        )
        if service_result.scalar_one_or_none():
            return vehicle

    # skip_test() never returns - it raises Skipped exception
    skip_test(
        "No vehicles with service records found. Please add service records first."
    )


@pytest_asyncio.fixture
async def vehicle_with_fuel_records(
    db_session: AsyncSession, test_user: dict[str, object]
) -> Vehicle:
    """Get a vehicle that has fuel records."""
    user_id = test_user["id"]
    # Find a vehicle with fuel records
    result = await db_session.execute(
        select(Vehicle).where(Vehicle.user_id == user_id).limit(10)
    )
    vehicles = result.scalars().all()

    for vehicle in vehicles:
        fuel_result = await db_session.execute(
            select(FuelRecord).where(FuelRecord.vin == vehicle.vin).limit(1)
        )
        if fuel_result.scalar_one_or_none():
            return vehicle

    # skip_test() never returns - it raises Skipped exception
    skip_test("No vehicles with fuel records found. Please add fuel records first.")


@pytest_asyncio.fixture
async def vehicle_with_analytics_data(
    db_session: AsyncSession, test_user: dict[str, object]
) -> Vehicle:
    """Get a vehicle that has sufficient data for analytics (service + fuel records)."""
    user_id = test_user["id"]
    # Find a vehicle with both service and fuel records
    result = await db_session.execute(
        select(Vehicle).where(Vehicle.user_id == user_id).limit(10)
    )
    vehicles = result.scalars().all()

    for vehicle in vehicles:
        service_result = await db_session.execute(
            select(ServiceRecord).where(ServiceRecord.vin == vehicle.vin).limit(1)
        )
        fuel_result = await db_session.execute(
            select(FuelRecord).where(FuelRecord.vin == vehicle.vin).limit(1)
        )

        if service_result.scalar_one_or_none() and fuel_result.scalar_one_or_none():
            return vehicle

    # skip_test() never returns - it raises Skipped exception
    skip_test(
        "No vehicles with both service and fuel records found. Please add more data first."
    )


@pytest.fixture
def auth_headers(test_user: dict[str, object]) -> dict[str, str]:
    """Provide authentication headers for API requests with valid JWT token.

    Note: For endpoints that require CSRF tokens (POST/PUT/DELETE),
    use login API to get both JWT and CSRF tokens instead.
    """
    from app.services.auth import create_access_token

    # Create a valid JWT token for the test user
    token = create_access_token(
        data={"sub": str(test_user["id"]), "username": str(test_user["username"])}
    )
    return {"Authorization": f"Bearer {token}"}

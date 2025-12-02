"""Pytest configuration and fixtures for MyGarage backend tests."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select
from typing import AsyncGenerator
import os

from app.main import app
from app.database import get_db, Base
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.service import ServiceRecord
from app.models.fuel import FuelRecord


# Test database URL - defaults to SQLite for isolated testing
# Override with TEST_DATABASE_URL environment variable if needed
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "sqlite+aiosqlite:///./test_mygarage.db"
)


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create async engine for tests."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def test_sessionmaker(test_engine):
    """Create session maker for tests."""
    return async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False
    )


@pytest_asyncio.fixture(scope="session")
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
async def db_session(test_sessionmaker) -> AsyncGenerator[AsyncSession, None]:
    """Provide a database session for tests."""
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
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac

    # Clean up overrides
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession, init_test_db) -> User:
    """Create or get a test user."""
    from app.services.auth import hash_password

    # Try to get existing test user
    result = await db_session.execute(
        select(User).where(User.email == "testuser@example.com")
    )
    user = result.scalar_one_or_none()

    if not user:
        # Create test user
        user = User(
            email="testuser@example.com",
            password_hash=hash_password("TestPassword123!"),
            is_active=True
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

    return user


@pytest_asyncio.fixture
async def test_vehicle(db_session: AsyncSession, test_user: User) -> Vehicle:
    """Create or get a test vehicle."""
    # Try to get existing test vehicle
    result = await db_session.execute(
        select(Vehicle).where(Vehicle.user_id == test_user.id)
    )
    vehicle = result.scalar_one_or_none()

    if not vehicle:
        # Create test vehicle
        vehicle = Vehicle(
            vin="1HGBH41JXMN109186",
            user_id=test_user.id,
            nickname="Test Vehicle",
            vehicle_type="Car",
            year=2018,
            make="Honda",
            model="Accord"
        )
        db_session.add(vehicle)
        await db_session.commit()
        await db_session.refresh(vehicle)

    return vehicle


@pytest_asyncio.fixture
async def vehicle_with_service_records(db_session: AsyncSession, test_user: User) -> Vehicle:
    """Get a vehicle that has service records."""
    # Find a vehicle with service records
    result = await db_session.execute(
        select(Vehicle)
        .where(Vehicle.user_id == test_user.id)
        .limit(10)
    )
    vehicles = result.scalars().all()

    for vehicle in vehicles:
        service_result = await db_session.execute(
            select(ServiceRecord)
            .where(ServiceRecord.vin == vehicle.vin)
            .limit(1)
        )
        if service_result.scalar_one_or_none():
            return vehicle

    pytest.skip("No vehicles with service records found. Please add service records first.")


@pytest_asyncio.fixture
async def vehicle_with_fuel_records(db_session: AsyncSession, test_user: User) -> Vehicle:
    """Get a vehicle that has fuel records."""
    # Find a vehicle with fuel records
    result = await db_session.execute(
        select(Vehicle)
        .where(Vehicle.user_id == test_user.id)
        .limit(10)
    )
    vehicles = result.scalars().all()

    for vehicle in vehicles:
        fuel_result = await db_session.execute(
            select(FuelRecord)
            .where(FuelRecord.vin == vehicle.vin)
            .limit(1)
        )
        if fuel_result.scalar_one_or_none():
            return vehicle

    pytest.skip("No vehicles with fuel records found. Please add fuel records first.")


@pytest_asyncio.fixture
async def vehicle_with_analytics_data(db_session: AsyncSession, test_user: User) -> Vehicle:
    """Get a vehicle that has sufficient data for analytics (service + fuel records)."""
    # Find a vehicle with both service and fuel records
    result = await db_session.execute(
        select(Vehicle)
        .where(Vehicle.user_id == test_user.id)
        .limit(10)
    )
    vehicles = result.scalars().all()

    for vehicle in vehicles:
        service_result = await db_session.execute(
            select(ServiceRecord)
            .where(ServiceRecord.vin == vehicle.vin)
            .limit(1)
        )
        fuel_result = await db_session.execute(
            select(FuelRecord)
            .where(FuelRecord.vin == vehicle.vin)
            .limit(1)
        )

        if service_result.scalar_one_or_none() and fuel_result.scalar_one_or_none():
            return vehicle

    pytest.skip("No vehicles with both service and fuel records found. Please add more data first.")


@pytest.fixture
def auth_headers(test_user: User) -> dict:
    """Provide authentication headers for API requests."""
    # Note: In a real scenario, you'd generate a proper JWT token
    # For testing purposes, you might bypass auth or use a test token
    return {
        "X-Test-User-Id": str(test_user.id)
    }

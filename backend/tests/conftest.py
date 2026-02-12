"""Pytest configuration and fixtures for MyGarage backend tests."""

import os
import shutil
import tempfile
from pathlib import Path

# Enable test mode BEFORE importing app (disables CSRF validation in middleware)
os.environ["MYGARAGE_TEST_MODE"] = "true"

from collections.abc import AsyncGenerator
from typing import NoReturn

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.fuel import FuelRecord
from app.models.service_visit import ServiceVisit
from app.models.user import User
from app.models.vehicle import Vehicle


def skip_test(reason: str) -> NoReturn:
    """Skip test with given reason - typed to indicate it never returns."""
    pytest.skip(reason)
    raise AssertionError("pytest.skip should have raised")


# Test database URL - defaults to SQLite for isolated testing
# Override with TEST_DATABASE_URL environment variable if needed
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "sqlite+aiosqlite:///./test_mygarage.db")


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
async def db_session(test_sessionmaker, init_test_db) -> AsyncGenerator[AsyncSession]:
    """Provide a database session for tests. Depends on init_test_db to ensure tables exist."""
    async with test_sessionmaker() as session:
        yield session


@pytest.fixture(scope="session")
def test_data_dir():
    """Create a temporary data directory for file upload tests.

    This fixture is session-scoped to avoid recreating directories for every test.
    """
    # Create temp directory structure
    tmp_dir = Path(tempfile.mkdtemp(prefix="mygarage_test_"))
    photos_dir = tmp_dir / "photos"
    documents_dir = tmp_dir / "documents"
    attachments_dir = tmp_dir / "attachments"

    photos_dir.mkdir(exist_ok=True)
    documents_dir.mkdir(exist_ok=True)
    attachments_dir.mkdir(exist_ok=True)

    yield tmp_dir

    # Cleanup after all tests
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest_asyncio.fixture
async def client(db_session, test_data_dir: Path) -> AsyncGenerator[AsyncClient]:
    """Provide an async HTTP client for testing API endpoints."""
    from app.routes import documents as documents_route
    from app.routes import photos as photos_route
    from app.routes import window_sticker as window_sticker_route
    from app.services import file_upload_service

    # Override the get_db dependency to use our test session
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    # Patch settings to use temp directories for file uploads
    original_data_dir = settings.data_dir
    original_photos_dir = settings.photos_dir
    original_documents_dir = settings.documents_dir
    original_attachments_dir = settings.attachments_dir

    settings.data_dir = test_data_dir
    settings.photos_dir = test_data_dir / "photos"
    settings.documents_dir = test_data_dir / "documents"
    settings.attachments_dir = test_data_dir / "attachments"

    # Also patch the module-level upload configs (they cache settings at import time)
    original_photo_base_dir = file_upload_service.PHOTO_UPLOAD_CONFIG.base_dir
    original_document_base_dir = file_upload_service.DOCUMENT_UPLOAD_CONFIG.base_dir
    original_attachment_base_dir = file_upload_service.ATTACHMENT_UPLOAD_CONFIG.base_dir
    original_doc_storage_path = documents_route.DOCUMENT_STORAGE_PATH
    original_photo_dir = photos_route.PHOTO_DIR
    original_sticker_storage_path = window_sticker_route.STICKER_STORAGE_PATH

    file_upload_service.PHOTO_UPLOAD_CONFIG.base_dir = test_data_dir / "photos"
    file_upload_service.DOCUMENT_UPLOAD_CONFIG.base_dir = test_data_dir / "documents"
    file_upload_service.ATTACHMENT_UPLOAD_CONFIG.base_dir = test_data_dir / "attachments"
    documents_route.DOCUMENT_STORAGE_PATH = test_data_dir / "documents"
    photos_route.PHOTO_DIR = test_data_dir / "photos"
    window_sticker_route.STICKER_STORAGE_PATH = test_data_dir / "documents"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    # Restore original settings
    settings.data_dir = original_data_dir
    settings.photos_dir = original_photos_dir
    settings.documents_dir = original_documents_dir
    settings.attachments_dir = original_attachments_dir

    # Restore module-level configs
    file_upload_service.PHOTO_UPLOAD_CONFIG.base_dir = original_photo_base_dir
    file_upload_service.DOCUMENT_UPLOAD_CONFIG.base_dir = original_document_base_dir
    file_upload_service.ATTACHMENT_UPLOAD_CONFIG.base_dir = original_attachment_base_dir
    documents_route.DOCUMENT_STORAGE_PATH = original_doc_storage_path
    photos_route.PHOTO_DIR = original_photo_dir
    window_sticker_route.STICKER_STORAGE_PATH = original_sticker_storage_path

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
    test_password_hash = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"

    # Try to get existing test user (check both username and email for conflicts)
    result = await db_session.execute(
        select(User).where(or_(User.username == "testuser", User.email == "testuser@example.com"))
    )
    user = result.scalar_one_or_none()

    if not user:
        # Create test user
        user = User(
            username="testuser",
            email="testuser@example.com",
            hashed_password=test_password_hash,
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
    result = await db_session.execute(select(Vehicle).where(Vehicle.vin == test_vin))
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
    result = await db_session.execute(select(Vehicle).where(Vehicle.user_id == user_id).limit(10))
    vehicles = result.scalars().all()

    for vehicle in vehicles:
        service_result = await db_session.execute(
            select(ServiceVisit).where(ServiceVisit.vin == vehicle.vin).limit(1)
        )
        if service_result.scalar_one_or_none():
            return vehicle

    # skip_test() never returns - it raises Skipped exception
    skip_test("No vehicles with service visits found. Please add service visits first.")


@pytest_asyncio.fixture
async def vehicle_with_fuel_records(
    db_session: AsyncSession, test_user: dict[str, object]
) -> Vehicle:
    """Get a vehicle that has fuel records."""
    user_id = test_user["id"]
    # Find a vehicle with fuel records
    result = await db_session.execute(select(Vehicle).where(Vehicle.user_id == user_id).limit(10))
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
    result = await db_session.execute(select(Vehicle).where(Vehicle.user_id == user_id).limit(10))
    vehicles = result.scalars().all()

    for vehicle in vehicles:
        service_result = await db_session.execute(
            select(ServiceVisit).where(ServiceVisit.vin == vehicle.vin).limit(1)
        )
        fuel_result = await db_session.execute(
            select(FuelRecord).where(FuelRecord.vin == vehicle.vin).limit(1)
        )

        if service_result.scalar_one_or_none() and fuel_result.scalar_one_or_none():
            return vehicle

    # skip_test() never returns - it raises Skipped exception
    skip_test("No vehicles with both service visits and fuel records found.")


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

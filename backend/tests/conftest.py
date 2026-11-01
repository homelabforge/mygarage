"""Pytest configuration and fixtures for MyGarage backend tests."""

import logging
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

# Enable test mode BEFORE importing app (disables CSRF validation in middleware)
os.environ["MYGARAGE_TEST_MODE"] = "true"

# A fixed settings encryption key, so every secret write has a keyring. Without
# one, the first secret write would find no /data to generate a key in, and which
# tests 503 would depend on their order. It decodes to "mygarage test settings
# key 0001!"; the same value is in docker-compose.test.yml and playwright.config.ts.
# Tests that swap key sources call settings_crypto._reset_keyring_for_tests().
os.environ.setdefault("MYGARAGE_SETTINGS_KEY", "bXlnYXJhZ2UgdGVzdCBzZXR0aW5ncyBrZXkgMDAwMSE")

# Same for the JWT key: unset, importing app.config writes /data/secret.key on
# any host where /data is writable. Same value as docker-compose.test.yml.
os.environ.setdefault("MYGARAGE_SECRET_KEY", "test-secret-key")

# If TEST_DATABASE_URL is set (e.g. for PostgreSQL), propagate it to the app's
# database URL so the app engine matches the test engine. Must happen before imports.
if "TEST_DATABASE_URL" in os.environ:
    os.environ["MYGARAGE_DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

from collections.abc import AsyncGenerator, Generator, Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from slowapi import Limiter
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.main import limiter as main_limiter
from app.models.def_record import DEFRecord
from app.models.financing import FinancingRecord
from app.models.fuel import FuelRecord
from app.models.hours import HoursRecord
from app.models.odometer import OdometerRecord
from app.models.reminder import Reminder
from app.models.service_visit import ServiceVisit
from app.models.tax import TaxRecord
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.warranty import WarrantyRecord
from app.routes.analytics import limiter as analytics_limiter
from app.routes.auth import limiter as auth_limiter
from app.routes.export import limiter as export_limiter
from app.routes.fuel import limiter as fuel_limiter
from app.routes.garage_assistant import limiter as garage_assistant_limiter
from app.routes.import_data._common import limiter as import_limiter
from app.routes.oidc import limiter as oidc_limiter
from app.routes.webhooks import limiter as webhooks_limiter
from app.services.widget_auth import widget_limiter
from app.utils.pg_session import create_utc_async_engine
from tests._shard import apply_shard
from tests._users import TEST_PASSWORD_HASH


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Keep only this CI runner's share of the tests. A no-op off CI.

    trylast so -k and -m have already deselected, and the shards split
    what's actually left.
    """
    apply_shard(
        items,
        rootpath=config.rootpath,
        deselect=lambda dropped: config.hook.pytest_deselected(items=dropped),
        environ=os.environ,
    )


# Test database URL - defaults to SQLite for isolated testing
# Override with TEST_DATABASE_URL environment variable if needed
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "sqlite+aiosqlite:///./test_mygarage.db")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_engine():
    """Create async engine for tests.

    Uses NullPool for PostgreSQL/asyncpg to avoid event loop binding issues
    with starlette middleware sub-tasks in pytest. PG sessions are pinned to
    UTC like the app's, so a test reads what production would store.
    """
    pool_kwargs = {}
    if "asyncpg" in TEST_DATABASE_URL:
        pool_kwargs["poolclass"] = NullPool
    engine = create_utc_async_engine(TEST_DATABASE_URL, echo=False, **pool_kwargs)
    if "sqlite" in TEST_DATABASE_URL:
        # Mirror production connection pragmas (WAL + foreign_keys=ON) so FK
        # cascade behavior in tests matches the deployed engine.
        from app.database import configure_sqlite_engine

        configure_sqlite_engine(engine)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_sessionmaker(test_engine):
    """Create session maker for tests.

    `autoflush=False`, exactly as `app/database.py` builds production sessions.
    With the default the suite flushed before every query, so a service that
    added a row and then queried for it in the same unit of work passed every
    test and failed in production.
    """
    return async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )


#: Dated records the leak guard checks, each with the column that dates it. A
#: row on any of these a year out lands in every later test's "latest reading",
#: trend window, active warranty or due count.
FAR_FUTURE_GUARDED: tuple[tuple[type[Base], str], ...] = (
    (DEFRecord, "date"),
    (FinancingRecord, "date"),
    (FuelRecord, "date"),
    (HoursRecord, "date"),
    (OdometerRecord, "date"),
    (Reminder, "due_date"),
    (ServiceVisit, "date"),
    (TaxRecord, "date"),
    (WarrantyRecord, "end_date"),
)


def far_future_horizon() -> date:
    """Rows dated after this are far-future: a year past today, in UTC.

    UTC, not household time: no request is running at session end, so there's
    no household zone to read, and the container's TZ moves under
    `local_clock_off_utc`. A day either way is nothing against a year.
    """
    return datetime.now(UTC).date() + timedelta(days=365)


async def far_future_survivors(engine: AsyncEngine, horizon: date | None = None) -> list[str]:
    """One line per guarded row dated past the horizon: table, id, VIN and date.

    The horizon defaults to `far_future_horizon()`; a caller that has already
    read it passes it in, so a run crossing UTC midnight can't move it between.
    """
    horizon = horizon or far_future_horizon()
    found: list[str] = []
    async with engine.connect() as conn:
        for model, column_name in FAR_FUTURE_GUARDED:
            column = getattr(model, column_name)
            rows = await conn.execute(
                select(model.id, model.vin, column.label("dated"))
                .where(column > horizon)
                .order_by(model.vin, column, model.id)
            )
            found += [
                f"{model.__tablename__} id={row.id} vin={row.vin} {column_name}={row.dated}"
                for row in rows
            ]
    return found


async def finish_test_db(engine: AsyncEngine) -> None:
    """Session end: fail on any far-future survivor (R5), dropping the tables either way.

    The drop sits in a finally, so a guard query that blows up still leaves a
    clean database behind.
    """
    horizon = far_future_horizon()
    try:
        survivors = await far_future_survivors(engine, horizon)
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    if survivors:
        # This lands on whichever test ran last, so say it isn't that one's fault.
        pytest.fail(
            f"{len(survivors)} row(s) dated after {horizon} outlived their "
            "tests (checked at session end; the last test isn't necessarily the culprit). "
            "Find the test that writes this VIN and give its vehicle a teardown:\n"
            + "\n".join(f"  {line}" for line in survivors),
            pytrace=False,
        )


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def init_test_db(test_engine):
    """Initialize test database schema.

    At the end `finish_test_db` fails the run if any far-future row survived
    its test's teardown (R5), then drops the tables either way.
    """
    async with test_engine.begin() as conn:
        # Create all tables from SQLAlchemy models
        await conn.run_sync(Base.metadata.create_all)
    yield
    await finish_test_db(test_engine)


@pytest.fixture(autouse=True)
def _no_session_refresh_debounce() -> Generator[None]:
    """Run a closed session's queued refresh as soon as its commit lands.

    With the real debounce every test that commits a reading inside a closed
    window would park in the drain below for 2 to 30 s (B6-12, E-7). A test
    that measures the debounce sets the real values itself.
    """
    from app.services import telemetry_service

    saved = (
        telemetry_service.SESSION_REFRESH_DEBOUNCE_SECONDS,
        telemetry_service.SESSION_REFRESH_MAX_DELAY_SECONDS,
    )
    telemetry_service.SESSION_REFRESH_DEBOUNCE_SECONDS = 0.0
    telemetry_service.SESSION_REFRESH_MAX_DELAY_SECONDS = 0.0
    telemetry_service._REFRESH_DUE.clear()
    yield
    (
        telemetry_service.SESSION_REFRESH_DEBOUNCE_SECONDS,
        telemetry_service.SESSION_REFRESH_MAX_DELAY_SECONDS,
    ) = saved


@pytest_asyncio.fixture(autouse=True)
async def _finish_post_commit_jobs(_no_session_refresh_debounce: None) -> AsyncGenerator[None]:
    """Let the background jobs a test's commits queued finish before the next test.

    They run on the test loop, so one still running would send its
    notification into the next test's recorder (`app.services.post_commit`).
    Torn down before the debounce fixture, so the drain runs on its values.
    """
    yield
    from app.services.post_commit import drain

    await drain()


@pytest.fixture(autouse=True)
def _forget_rate_baselines() -> None:
    """Start every test with no remembered readings, as a fresh process would.

    The rate check keeps each device's last accepted reading in memory, and
    the suite reuses device ids and keys across tests.
    """
    from app.services.telemetry_validator import forget_accepted_readings

    forget_accepted_readings()


#: Every module-level slowapi Limiter in app/, by where it lives.
#: tests/unit/test_limiter_reset_inventory.py fails if a new one isn't here.
APP_LIMITERS: dict[str, Limiter] = {
    "app.main.limiter": main_limiter,
    "app.routes.analytics.limiter": analytics_limiter,
    "app.routes.auth.limiter": auth_limiter,
    "app.routes.export.limiter": export_limiter,
    "app.routes.fuel.limiter": fuel_limiter,
    "app.routes.garage_assistant.limiter": garage_assistant_limiter,
    "app.routes.import_data._common.limiter": import_limiter,
    "app.routes.oidc.limiter": oidc_limiter,
    "app.routes.webhooks.limiter": webhooks_limiter,
    "app.services.widget_auth.widget_limiter": widget_limiter,
}


@pytest.fixture(autouse=True)
def _reset_rate_limits() -> None:
    """Start every test with every rate limit unspent.

    The limiters are module globals keyed on the client address, and the whole
    suite comes from 127.0.0.1, so one file's requests could 429 the next file.
    """
    # Each reset logs an INFO line, and ten a test would bury the live log.
    # A storage that can't reset still gets its WARNING through.
    slowapi_log = logging.getLogger("slowapi")
    level = slowapi_log.level
    slowapi_log.setLevel(logging.WARNING)
    try:
        for limiter in APP_LIMITERS.values():
            limiter.reset()
    finally:
        slowapi_log.setLevel(level)


@pytest_asyncio.fixture
async def db_session(test_sessionmaker, init_test_db) -> AsyncGenerator[AsyncSession]:
    """Provide a database session for tests. Depends on init_test_db to ensure tables exist."""
    async with test_sessionmaker() as session:
        yield session


@pytest.fixture
def local_clock_off_utc() -> Iterator[None]:
    """Put the process clock five hours west of UTC for one test.

    A naive value fed to `astimezone` is read as LOCAL time, and a bare
    `datetime.now()` is local too, so in a UTC container either bug looks right
    and no test can tell. Its own MonkeyPatch, so undoing it can't undo the
    test's other patches.
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("TZ", "EST5")
        time.tzset()
        yield
    time.tzset()


@pytest_asyncio.fixture
async def keep_rows(db_session: AsyncSession):
    """Snapshot settings rows by key and put them back afterwards.

    The stored value, category, description and the encrypted flag come back;
    the row is recreated, so its created_at and updated_at do not. The raw
    `stored_value` is what comes back, not the decrypted `value`: going through
    `value` would turn an unreadable secret's ciphertext into None, and a
    restored legacy plaintext into fresh ciphertext.

    Call the yielded function with the keys a test is about to write. The test
    database is created without the seeded settings and persists for the whole
    run, so a test seeds what it needs and must not leave it behind. A key with
    no row before the test has none after it.
    """
    from app.models.settings import Setting

    saved: dict[str, tuple[str | None, str, str | None, bool] | None] = {}

    async def keep(*keys: str) -> None:
        for key in keys:
            if key in saved:
                continue
            row = await db_session.get(Setting, key)
            saved[key] = (
                None
                if row is None
                else (row.stored_value, row.category, row.description, row.encrypted)
            )

    yield keep
    await db_session.rollback()
    await db_session.execute(delete(Setting).where(Setting.key.in_(list(saved))))
    for key, snapshot in saved.items():
        if snapshot is not None:
            stored_value, category, description, encrypted = snapshot
            db_session.add(
                Setting(
                    key=key,
                    stored_value=stored_value,
                    category=category,
                    description=description,
                    encrypted=encrypted,
                )
            )
    await db_session.commit()


@pytest_asyncio.fixture
async def livelink_enabled(db_session: AsyncSession) -> AsyncGenerator[None]:
    """Switch LiveLink's master switch on for one test, then put it back.

    The switch gates every ingest path (`livelink_ingest.ingest`, the HTTPS
    route, SD backfill), and migration 034 seeds it off. A test that drives
    ingest without it asserts against an early return: "no session opened"
    passes for the wrong reason. Not autouse, because the tests pinning the
    switched-off behaviour must see the real default. The suite shares one
    database, so the prior value is restored.
    """
    from app.models.settings import Setting

    existing = await db_session.get(Setting, "livelink_enabled")
    previous = existing.value if existing is not None else None
    if existing is not None:
        existing.value = "true"
    else:
        db_session.add(Setting(key="livelink_enabled", value="true"))
    await db_session.commit()

    yield

    # A failed test can leave the session mid-transaction; restoring through
    # it would raise here and bury the real failure under a teardown error.
    await db_session.rollback()
    row = await db_session.get(Setting, "livelink_enabled")
    if previous is None:
        if row is not None:
            await db_session.delete(row)
    elif row is not None:
        row.value = previous
    await db_session.commit()


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
        # Mirror production `get_db`: a route's exception, HTTPException
        # included, is raised here after the yield, and the request's
        # flushed-but-uncommitted writes must not survive into the next
        # request or the test's own assertions.
        try:
            yield db_session
        except Exception:
            await db_session.rollback()
            raise

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
        # accent_color / theme leak between tests (a prior test may PUT an
        # explicit value, and null-on-PUT means "no change"), so reset to unset.
        user.accent_color = None
        user.theme = None
        user.dashboard_sort = "name"
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
            # Diesel so DEF-record routes (fuel-type gate, Task 5) accept it.
            # Fuel-record tests don't validate fuel_type_used against this.
            fuel_type="diesel",
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
async def own_vehicle(
    request: pytest.FixtureRequest, db_session: AsyncSession, test_user: dict[str, object]
) -> AsyncGenerator[Vehicle]:
    """A fresh vehicle, deleted afterwards with every record on it. What a test
    writes here would otherwise land in the test user's garage-wide totals.

    `@pytest.mark.own_vehicle(fuel_type="diesel", ...)` on a test, class or
    module overrides any of its columns.
    """
    marker = request.node.get_closest_marker("own_vehicle")
    fields: dict[str, object] = {
        "nickname": "Legacy Money",
        "vehicle_type": "Car",
        "year": 2015,
        "make": "Honda",
        "model": "Fit",
        **(marker.kwargs if marker is not None else {}),
    }
    vehicle = Vehicle(vin="LEG" + uuid.uuid4().hex[:14].upper(), user_id=test_user["id"], **fields)
    db_session.add(vehicle)
    await db_session.commit()
    vin = vehicle.vin
    yield vehicle
    # A failed read rolls the session back, so look the vehicle up again.
    await db_session.rollback()
    stored = await db_session.get(Vehicle, vin)
    if stored is not None:
        await db_session.delete(stored)
        await db_session.commit()


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


@pytest_asyncio.fixture
async def non_admin_user(db_session: AsyncSession) -> dict[str, object]:
    """Create a non-admin test user for authorization testing.

    Unlike test_user (which is admin), this user has no admin privileges.
    Used to verify that non-owners get 403 when accessing other users' vehicles.
    """
    from sqlalchemy import or_

    result = await db_session.execute(
        select(User).where(
            or_(User.username == "nonadminuser", User.email == "nonadminuser@example.com")
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            username="nonadminuser",
            email="nonadminuser@example.com",
            hashed_password=TEST_PASSWORD_HASH,
            is_active=True,
            is_admin=False,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
    else:
        user.is_active = True
        user.is_admin = False
        await db_session.commit()
        await db_session.refresh(user)

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_active": user.is_active,
        "is_admin": user.is_admin,
    }


@pytest.fixture
def non_admin_headers(non_admin_user: dict[str, object]) -> dict[str, str]:
    """Auth headers for the non-admin user. Used for 403 authorization tests."""
    from app.services.auth import create_access_token

    token = create_access_token(
        data={"sub": str(non_admin_user["id"]), "username": str(non_admin_user["username"])}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _reset_household_zone():
    """Per-test reset of the household-zone globals (plan 4.7)."""
    from app.utils import household_time

    household_time.household_zone_var.set(None)
    household_time._warned_values.clear()
    yield
    household_time.household_zone_var.set(None)

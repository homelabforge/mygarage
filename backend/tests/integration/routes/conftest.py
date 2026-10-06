"""Shared fixtures for vehicle-authorization negative tests (v2.28.0 hardening).

These build a full local-mode authorization matrix around a single owned
vehicle so the negative-authz tests (the primary regression protection per the
plan §15) can assert owner / read-share / write-share / unrelated / admin
behaviour without each test re-creating users and shares.

Auth mode: tests run in the default ``local`` mode (no ``auth_mode`` Setting
row => get_auth_mode returns ``local``), so ``require_auth`` /
``get_current_admin_user`` enforce. The ``set_auth_mode`` helper flips it to
``none`` for the legacy-behaviour regression cases.
"""

import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import parse_client_ip_header, parse_trusted_proxies, settings
from app.main import app
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_share import VehicleShare

# Pre-computed argon2 hash for "testpassword123" (matches base conftest); avoids
# calling hash_password() which needs threads (fails in PID-limited containers).
_PWHASH = "$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI"


async def _get_or_create_user(db: AsyncSession, username: str, *, is_admin: bool = False) -> User:
    from sqlalchemy import or_

    email = f"{username}@example.com"
    result = await db.execute(
        select(User).where(or_(User.username == username, User.email == email))
    )
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            username=username,
            email=email,
            hashed_password=_PWHASH,
            is_active=True,
            is_admin=is_admin,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    else:
        user.is_active = True
        user.is_admin = is_admin
        await db.commit()
        await db.refresh(user)
    return user


def _headers(user: User) -> dict[str, str]:
    from app.services.auth import create_access_token

    token = create_access_token(data={"sub": str(user.id), "username": user.username})
    return {"Authorization": f"Bearer {token}"}


# --- Users -------------------------------------------------------------------


@pytest_asyncio.fixture
async def owner_user(db_session: AsyncSession) -> User:
    """A non-admin user who owns the authz test vehicle."""
    return await _get_or_create_user(db_session, "authz_owner", is_admin=False)


@pytest_asyncio.fixture
async def reader_user(db_session: AsyncSession) -> User:
    """A non-admin user granted a READ share on the authz vehicle."""
    return await _get_or_create_user(db_session, "authz_reader", is_admin=False)


@pytest_asyncio.fixture
async def writer_user(db_session: AsyncSession) -> User:
    """A non-admin user granted a WRITE share on the authz vehicle."""
    return await _get_or_create_user(db_session, "authz_writer", is_admin=False)


@pytest_asyncio.fixture
async def unrelated_user(db_session: AsyncSession) -> User:
    """A non-admin user with no relationship to the authz vehicle."""
    return await _get_or_create_user(db_session, "authz_unrelated", is_admin=False)


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    """A separate admin user (not the vehicle owner)."""
    return await _get_or_create_user(db_session, "authz_admin", is_admin=True)


# --- The owned vehicle + shares ----------------------------------------------

AUTHZ_VIN = "WAUZZZ8K9AA000001"


@pytest_asyncio.fixture
async def owned_vehicle(
    db_session: AsyncSession,
    owner_user: User,
    reader_user: User,
    writer_user: User,
) -> Vehicle:
    """A vehicle owned by ``owner_user`` with a read-share and a write-share.

    Cleans any prior shares so the read/write split is deterministic.
    """
    # Reset these on a reused row too. A rename test elsewhere left
    # "Renamed" behind and search for "Authz" came back empty.
    fields = {
        "user_id": owner_user.id,
        "nickname": "Authz Test Vehicle",
        "vehicle_type": "Car",
        "year": 2010,
        "make": "Audi",
        "model": "A4",
        "archived_at": None,
    }
    result = await db_session.execute(select(Vehicle).where(Vehicle.vin == AUTHZ_VIN))
    vehicle = result.scalar_one_or_none()
    if vehicle is None:
        vehicle = Vehicle(vin=AUTHZ_VIN, **fields)
        db_session.add(vehicle)
    else:
        for name, value in fields.items():
            setattr(vehicle, name, value)
    await db_session.execute(delete(VehicleShare).where(VehicleShare.vehicle_vin == AUTHZ_VIN))
    db_session.add(
        VehicleShare(
            vehicle_vin=AUTHZ_VIN,
            user_id=reader_user.id,
            permission="read",
            shared_by=owner_user.id,
        )
    )
    db_session.add(
        VehicleShare(
            vehicle_vin=AUTHZ_VIN,
            user_id=writer_user.id,
            permission="write",
            shared_by=owner_user.id,
        )
    )
    await db_session.commit()
    await db_session.refresh(vehicle)
    return vehicle


# --- A throwaway vehicle for legacy-row reads ---------------------------------


@pytest_asyncio.fixture
async def own_vehicle(
    db_session: AsyncSession, test_user: dict[str, object]
) -> AsyncGenerator[Vehicle]:
    """A fresh vehicle, deleted afterwards with every record on it. What a test
    writes here would otherwise land in the test user's garage-wide totals."""
    vehicle = Vehicle(
        vin="LEG" + uuid.uuid4().hex[:14].upper(),
        user_id=test_user["id"],
        nickname="Legacy Money",
        vehicle_type="Car",
        year=2015,
        make="Honda",
        model="Fit",
    )
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


# --- Header fixtures ----------------------------------------------------------


@pytest.fixture
def owner_headers(owner_user: User) -> dict[str, str]:
    return _headers(owner_user)


@pytest.fixture
def reader_headers(reader_user: User) -> dict[str, str]:
    return _headers(reader_user)


@pytest.fixture
def writer_headers(writer_user: User) -> dict[str, str]:
    return _headers(writer_user)


@pytest.fixture
def unrelated_headers(unrelated_user: User) -> dict[str, str]:
    return _headers(unrelated_user)


@pytest.fixture
def admin_user_headers(admin_user: User) -> dict[str, str]:
    return _headers(admin_user)


# --- auth_mode helper ---------------------------------------------------------


@pytest_asyncio.fixture
async def set_auth_mode(
    db_session: AsyncSession,
) -> Callable[[str], Awaitable[None]]:
    """Return an async setter for the ``auth_mode`` Setting; restores to local."""
    from app.models.settings import Setting

    async def _set(mode: str) -> None:
        result = await db_session.execute(select(Setting).where(Setting.key == "auth_mode"))
        setting = result.scalar_one_or_none()
        if setting is None:
            db_session.add(Setting(key="auth_mode", value=mode))
        else:
            setting.value = mode
        await db_session.commit()

    yield _set

    # Restore default (delete the row -> get_auth_mode falls back to 'local').
    result = await db_session.execute(select(Setting).where(Setting.key == "auth_mode"))
    setting = result.scalar_one_or_none()
    if setting is not None:
        await db_session.delete(setting)
        await db_session.commit()


# --- Trusted proxy -------------------------------------------------------------


@pytest.fixture
def trust_proxies(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Return ``trust(networks, *, header="")``, which sets the two proxy settings for one test.

    They go through the same parsers their env vars do, and ``monkeypatch`` puts
    them back afterwards.
    """

    def trust(networks: str, *, header: str = "") -> None:
        monkeypatch.setattr(settings, "trusted_proxies", parse_trusted_proxies(networks))
        monkeypatch.setattr(settings, "client_ip_header", parse_client_ip_header(header))

    return trust


@pytest_asyncio.fixture
async def client_via(client: AsyncClient) -> AsyncIterator[Callable[[str], AsyncClient]]:
    """Return ``make(peer)``, a client whose requests arrive from TCP peer ``peer``.

    Asks for ``client`` only for its ``get_db`` override and temp upload dirs.
    Every client it makes is closed at teardown.
    """
    made: list[AsyncClient] = []

    def make(peer: str) -> AsyncClient:
        # ASGITransport's client= is what lands in scope["client"].
        via = AsyncClient(
            transport=ASGITransport(app=app, client=(peer, 40000)), base_url="http://test"
        )
        made.append(via)
        return via

    yield make
    for via in made:
        await via.aclose()

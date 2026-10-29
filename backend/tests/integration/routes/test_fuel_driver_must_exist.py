"""A fill-up's driver must be a user here: 422, not a 409 that reads as a duplicate (batch 3b task 15, B3-1)."""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.database import get_db
from app.main import app
from app.models.fuel import FuelRecord
from app.models.user import User

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_NO_SUCH_USER = "driver_user_id: no such user"


async def _missing_user_id(db: AsyncSession) -> int:
    """An id past every user, so it names nobody."""
    return (await db.execute(select(func.max(User.id)))).scalar_one() + 1000


def _fill_up(vin: str, **fields: object) -> dict[str, object]:
    return {"vin": vin, "date": "2032-02-10", "odometer_km": 5000, "liters": 40.0, **fields}


@pytest_asyncio.fixture
async def pre_054_sqlite(
    client: AsyncClient,
    new_vehicle: Callable[..., Awaitable[str]],
    test_engine: AsyncEngine,
) -> AsyncIterator[AsyncSession]:
    """Run the app's requests on a SQLite connection with foreign keys off.

    That's an install from before 054, which added the driver column on SQLite
    with no FK. Asks for client and new_vehicle so it tears down before them.
    """
    if test_engine.dialect.name != "sqlite":
        pytest.skip("PostgreSQL got the driver FK in 054")
    conn = await test_engine.connect()
    try:
        await conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        await conn.commit()
        keys_on = (await conn.exec_driver_sql("PRAGMA foreign_keys")).scalar_one()
        await conn.commit()
        assert keys_on == 0, "fixture must start with no FK, like a pre-054 install"
        session = AsyncSession(bind=conn, expire_on_commit=False, autoflush=False)
        saved = app.dependency_overrides[get_db]

        async def override() -> AsyncIterator[AsyncSession]:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

        app.dependency_overrides[get_db] = override
        try:
            yield session
        finally:
            app.dependency_overrides[get_db] = saved
            await session.close()
    finally:
        # Bin the connection so the pool never hands out one with the keys off.
        await conn.invalidate()
        await conn.close()


async def test_create_refuses_a_driver_who_isnt_a_user(
    client: AsyncClient,
    auth_headers: dict[str, str],
    new_vehicle: Callable[..., Awaitable[str]],
    db_session: AsyncSession,
) -> None:
    vin = await new_vehicle()
    missing = await _missing_user_id(db_session)

    r = await client.post(
        f"/api/vehicles/{vin}/fuel",
        json=_fill_up(vin, driver_user_id=missing),
        headers=auth_headers,
    )

    # main: 409 "Duplicate or invalid fuel record", from the FK
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == _NO_SUCH_USER
    count = await db_session.execute(
        select(func.count()).select_from(FuelRecord).where(FuelRecord.vin == vin)
    )
    assert count.scalar_one() == 0


async def test_update_refuses_a_driver_who_isnt_a_user(
    client: AsyncClient,
    auth_headers: dict[str, str],
    new_vehicle: Callable[..., Awaitable[str]],
    db_session: AsyncSession,
    test_user: dict[str, object],
) -> None:
    vin = await new_vehicle()
    created = await client.post(
        f"/api/vehicles/{vin}/fuel",
        json=_fill_up(vin, driver_user_id=test_user["id"]),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    record_id = created.json()["id"]
    missing = await _missing_user_id(db_session)

    r = await client.put(
        f"/api/vehicles/{vin}/fuel/{record_id}",
        json={"driver_user_id": missing},
        headers=auth_headers,
    )

    # main: 409 "Database constraint violation"
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == _NO_SUCH_USER
    reread = await client.get(f"/api/vehicles/{vin}/fuel/{record_id}", headers=auth_headers)
    assert reread.json()["driver_user_id"] == test_user["id"]


async def test_a_former_member_can_still_be_the_driver(
    client: AsyncClient,
    auth_headers: dict[str, str],
    new_vehicle: Callable[..., Awaitable[str]],
    db_session: AsyncSession,
) -> None:
    """Guard (passes on main): active doesn't matter, a backdated fill-up can name someone who left."""
    # Kills an is_active filter in the driver check. A user who left still drove those miles.
    vin = await new_vehicle()
    former = User(
        username="b3b_former_driver_" + uuid.uuid4().hex[:6],
        email=f"former-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="x",
        is_active=False,
        is_admin=False,
    )
    db_session.add(former)
    await db_session.commit()
    former_id = former.id

    try:
        r = await client.post(
            f"/api/vehicles/{vin}/fuel",
            json=_fill_up(vin, driver_user_id=former_id),
            headers=auth_headers,
        )

        assert r.status_code == 201, r.text
        assert r.json()["driver_user_id"] == former_id
    finally:
        # The suite shares one database, so don't leave a stray user behind.
        await db_session.rollback()
        await db_session.execute(delete(User).where(User.id == former_id))
        await db_session.commit()


async def test_an_edit_that_resends_a_dangling_driver_keeps_it(
    client: AsyncClient,
    auth_headers: dict[str, str],
    new_vehicle: Callable[..., Awaitable[str]],
    test_user: dict[str, object],
    pre_054_sqlite: AsyncSession,
) -> None:
    """S13: only a changed driver is checked.

    A pre-054 SQLite install can hold a driver whose user is gone, and the fuel
    form sends it back on every save, so a notes fix still has to go through.
    """
    vin = await new_vehicle()
    created = await client.post(
        f"/api/vehicles/{vin}/fuel",
        json=_fill_up(vin, driver_user_id=test_user["id"]),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    record_id = created.json()["id"]
    missing = await _missing_user_id(pre_054_sqlite)
    await pre_054_sqlite.execute(
        text("UPDATE fuel_records SET driver_user_id = :driver WHERE id = :id"),
        {"driver": missing, "id": record_id},
    )
    await pre_054_sqlite.commit()
    pre_054_sqlite.expire_all()

    r = await client.put(
        f"/api/vehicles/{vin}/fuel/{record_id}",
        json={"notes": "fixed a typo", "driver_user_id": missing},
        headers=auth_headers,
    )

    # Checking every resent driver: 422 "driver_user_id: no such user"
    assert r.status_code == 200, r.text
    assert r.json()["notes"] == "fixed a typo"
    assert r.json()["driver_user_id"] == missing


async def test_deleting_a_user_clears_them_as_driver(
    client: AsyncClient,
    auth_headers: dict[str, str],
    new_vehicle: Callable[..., Awaitable[str]],
    db_session: AsyncSession,
    pre_054_sqlite: AsyncSession,
) -> None:
    """With no FK to do it, deleting a user has to clear their fill-ups' driver itself."""
    vin = await new_vehicle()
    leaver = User(
        username="b3b_leaving_driver_" + uuid.uuid4().hex[:6],
        email=f"leaving-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="x",
        is_active=True,
        is_admin=False,
    )
    db_session.add(leaver)
    await db_session.commit()
    leaver_id = leaver.id

    try:
        created = await client.post(
            f"/api/vehicles/{vin}/fuel",
            json=_fill_up(vin, driver_user_id=leaver_id),
            headers=auth_headers,
        )
        assert created.status_code == 201, created.text
        record_id = created.json()["id"]

        gone = await client.delete(f"/api/auth/users/{leaver_id}", headers=auth_headers)
        assert gone.status_code == 204, gone.text
        pre_054_sqlite.expire_all()

        reread = await client.get(f"/api/vehicles/{vin}/fuel/{record_id}", headers=auth_headers)
        # main: the deleted user's id stays on the fill-up
        assert reread.json()["driver_user_id"] is None
    finally:
        await db_session.rollback()
        await db_session.execute(delete(User).where(User.id == leaver_id))
        await db_session.commit()

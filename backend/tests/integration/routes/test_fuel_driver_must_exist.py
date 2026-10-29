"""A fill-up's driver must be a user here: 422, not a 409 that reads as a duplicate (batch 3b task 15, B3-1)."""

import uuid
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fuel import FuelRecord
from app.models.user import User

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_NO_SUCH_USER = "driver_user_id: no such user"


async def _missing_user_id(db: AsyncSession) -> int:
    """An id past every user, so it names nobody."""
    return (await db.execute(select(func.max(User.id)))).scalar_one() + 1000


def _fill_up(vin: str, **fields: object) -> dict[str, object]:
    return {"vin": vin, "date": "2032-02-10", "odometer_km": 5000, "liters": 40.0, **fields}


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

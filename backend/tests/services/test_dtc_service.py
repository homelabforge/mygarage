"""Tests for DTCService: how a code that comes back after a clear is recorded."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_dtc import VehicleDTC
from app.services.dtc_service import DTCService


async def _make_vehicle(db_session: AsyncSession) -> str:
    """Create a minimal user + vehicle, return the (unique) vin."""
    n = uuid.uuid4().hex[:11].upper()
    user = User(
        username=f"dtc_svc_user_{n}",
        email=f"dtc_svc_{n}@example.com",
        hashed_password="x",
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.flush()

    vin = f"DTCSVC{n}"  # 17 chars
    vehicle = Vehicle(
        vin=vin,
        user_id=user.id,
        nickname=f"DTC Svc Car {n}",
        vehicle_type="Car",
    )
    db_session.add(vehicle)
    await db_session.flush()
    return vin


@pytest.mark.asyncio
async def test_a_code_back_after_a_clear_gets_a_new_row(db_session: AsyncSession):
    """The cleared row stays as history and the returning code is a new active row."""
    vin = await _make_vehicle(db_session)
    service = DTCService(db_session)

    [first] = await service.process_dtcs(vin, "dtc-svc-dev", ["P0420"])
    await db_session.commit()
    first_id = first.id
    await service.clear_dtc(first_id)

    [second] = await service.process_dtcs(vin, "dtc-svc-dev", ["P0420"])
    await db_session.commit()
    second_id = second.id

    db_session.expire_all()
    rows = (
        (
            await db_session.execute(
                select(VehicleDTC)
                .where(VehicleDTC.vin == vin, VehicleDTC.code == "P0420")
                .order_by(VehicleDTC.id)
            )
        )
        .scalars()
        .all()
    )
    assert [r.id for r in rows] == [first_id, second_id]
    assert first_id != second_id
    cleared, active = rows
    assert cleared.is_active is False
    assert cleared.cleared_at is not None
    assert active.is_active is True
    assert active.cleared_at is None


@pytest.mark.asyncio
async def test_a_code_listed_twice_is_one_row(db_session: AsyncSession):
    """Regression guard (carry 2): the second copy finds the row the first one
    made, because `_create_vehicle_dtc` flushes (the session doesn't autoflush).
    The parser drops repeats too, so only a direct call shows this. Kills
    dropping that flush."""
    vin = await _make_vehicle(db_session)

    first, second = await DTCService(db_session).process_dtcs(
        vin, "dtc-svc-dev", ["P0301", "P0301"]
    )
    await db_session.flush()

    rows = (
        (
            await db_session.execute(
                select(VehicleDTC).where(VehicleDTC.vin == vin, VehicleDTC.code == "P0301")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert first is second

"""Tests for TorqueService: Torque Pro source lifecycle (create + resolve)."""

import itertools

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.livelink_service import LiveLinkService
from app.services.torque_service import TorqueService

# Module-level counter for unique identifiers across all tests in this file.
_SEQ = itertools.count()


async def _make_vehicle(db_session: AsyncSession) -> str:
    """Create a minimal user + vehicle, return the (unique) vin."""
    n = next(_SEQ)
    user = User(
        username=f"torque_svc_user_{n}",
        email=f"torque_svc_{n}@example.com",
        hashed_password="x",
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.flush()

    vin = f"TORQSVCTEST{n:06d}"  # 17 chars
    vehicle = Vehicle(
        vin=vin,
        user_id=user.id,
        nickname=f"Torque Svc Car {n}",
        vehicle_type="Car",
    )
    db_session.add(vehicle)
    await db_session.flush()
    return vin


@pytest.mark.asyncio
async def test_create_source_creates_a_torque_device(db_session: AsyncSession):
    """create_source persists a kind='torque' device with a hashed token."""
    vin = await _make_vehicle(db_session)

    device, raw_token = await TorqueService(db_session).create_source(vin)
    await db_session.commit()

    assert device.kind == "torque"
    assert device.vin == vin
    assert device.device_id.startswith("tq_")
    assert raw_token  # non-empty, shown once
    assert device.device_token_hash == LiveLinkService.hash_token(raw_token)


@pytest.mark.asyncio
async def test_resolve_by_token_returns_the_created_device(db_session: AsyncSession):
    """resolve_by_token finds the device by its raw token."""
    vin = await _make_vehicle(db_session)
    device, raw_token = await TorqueService(db_session).create_source(vin)
    await db_session.commit()

    resolved = await TorqueService(db_session).resolve_by_token(raw_token)

    assert resolved is not None
    assert resolved.device_id == device.device_id


@pytest.mark.asyncio
async def test_resolve_by_token_wrong_token_returns_none(db_session: AsyncSession):
    """An unrecognized token resolves to None."""
    vin = await _make_vehicle(db_session)
    await TorqueService(db_session).create_source(vin)
    await db_session.commit()

    resolved = await TorqueService(db_session).resolve_by_token("ll_wrong")

    assert resolved is None


@pytest.mark.asyncio
async def test_resolve_by_token_does_not_resolve_a_wican_devices_token(
    db_session: AsyncSession,
):
    """kind filter: a WiCAN device's token must not resolve via resolve_by_token."""
    vin = await _make_vehicle(db_session)
    wican_token = LiveLinkService.generate_token()
    wican_device = await LiveLinkService(db_session).auto_discover_device(
        device_id=f"wc{next(_SEQ):010d}"
    )
    device, _is_new = wican_device
    device.vin = vin
    device.device_token_hash = LiveLinkService.hash_token(wican_token)
    await db_session.commit()

    resolved = await TorqueService(db_session).resolve_by_token(wican_token)

    assert resolved is None


@pytest.mark.asyncio
async def test_two_create_source_calls_yield_distinct_devices(db_session: AsyncSession):
    """Two create_source calls produce distinct device_ids and distinct tokens."""
    vin = await _make_vehicle(db_session)
    service = TorqueService(db_session)

    device1, token1 = await service.create_source(vin)
    device2, token2 = await service.create_source(vin)
    await db_session.commit()

    assert device1.device_id != device2.device_id
    assert token1 != token2

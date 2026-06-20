"""Tests for auto-trigger SD backfill on device offline→online transition."""

import itertools

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.livelink_service import LiveLinkService

# Module-level counter for unique identifiers across all tests
_TRIGGER_SEQ = itertools.count()


@pytest_asyncio.fixture
async def make_trigger_device(db_session: AsyncSession):
    """Factory: creates a minimal user, vehicle, and LiveLinkDevice with device_status."""

    async def _factory(
        session: AsyncSession,
        *,
        device_address: str | None = None,
        sd_backfill_enabled: bool = False,
        device_status: str = "offline",
    ) -> tuple[str, str]:
        n = next(_TRIGGER_SEQ)

        user = User(
            username=f"trigger_user_{n}",
            email=f"trigger_{n}@example.com",
            hashed_password="x",
            is_active=True,
            is_admin=False,
        )
        session.add(user)
        await session.flush()

        vin = f"TRIGGERTEST{n:06d}"  # 17 chars
        vehicle = Vehicle(
            vin=vin,
            user_id=user.id,
            nickname=f"Trigger Car {n}",
            vehicle_type="Car",
        )
        session.add(vehicle)
        await session.flush()

        device_id = f"trig{n:010d}"  # unique, <=20 chars
        device = LiveLinkDevice(
            device_id=device_id,
            vin=vin,
            enabled=True,
            device_address=device_address,
            sd_backfill_enabled=sd_backfill_enabled,
            device_status=device_status,
        )
        session.add(device)
        await session.flush()

        return vin, device_id

    return _factory


@pytest.mark.asyncio
async def test_offline_to_online_enqueues_backfill(db_session, make_trigger_device, monkeypatch):
    """Offline device with address+enabled=True → online triggers enqueue."""
    vin, device_id = await make_trigger_device(
        db_session,
        device_address="10.10.20.244",
        sd_backfill_enabled=True,
        device_status="offline",
    )
    calls = []
    monkeypatch.setattr(
        "app.services.livelink_service.enqueue_sd_backfill",
        lambda did: calls.append(did),
    )
    await LiveLinkService(db_session).update_device_status(
        device_id=device_id, device_status="online"
    )
    assert calls == [device_id]


@pytest.mark.asyncio
async def test_no_enqueue_when_sd_disabled(db_session, make_trigger_device, monkeypatch):
    """sd_backfill_enabled=False → no enqueue even when going online."""
    vin, device_id = await make_trigger_device(
        db_session,
        device_address="10.10.20.244",
        sd_backfill_enabled=False,
        device_status="offline",
    )
    calls = []
    monkeypatch.setattr(
        "app.services.livelink_service.enqueue_sd_backfill",
        lambda did: calls.append(did),
    )
    await LiveLinkService(db_session).update_device_status(
        device_id=device_id, device_status="online"
    )
    assert calls == []


@pytest.mark.asyncio
async def test_no_enqueue_without_device_address(db_session, make_trigger_device, monkeypatch):
    """device_address=None → no enqueue even when going online with enabled=True."""
    vin, device_id = await make_trigger_device(
        db_session,
        device_address=None,
        sd_backfill_enabled=True,
        device_status="offline",
    )
    calls = []
    monkeypatch.setattr(
        "app.services.livelink_service.enqueue_sd_backfill",
        lambda did: calls.append(did),
    )
    await LiveLinkService(db_session).update_device_status(
        device_id=device_id, device_status="online"
    )
    assert calls == []


@pytest.mark.asyncio
async def test_no_enqueue_when_already_online(db_session, make_trigger_device, monkeypatch):
    """Device already online → setting online again is not a transition, no enqueue."""
    vin, device_id = await make_trigger_device(
        db_session,
        device_address="10.10.20.244",
        sd_backfill_enabled=True,
        device_status="online",
    )
    calls = []
    monkeypatch.setattr(
        "app.services.livelink_service.enqueue_sd_backfill",
        lambda did: calls.append(did),
    )
    await LiveLinkService(db_session).update_device_status(
        device_id=device_id, device_status="online"
    )
    assert calls == []

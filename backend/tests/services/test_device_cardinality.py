"""Tests for R1-H1: multi-device-per-vin cardinality reconciliation.

Task 5 (Torque source) introduces a second `livelink_devices` row per vehicle:
a vin may now have both a WiCAN device and a Torque device. These tests prove
the two `LiveLinkService` call sites that used to assume "at most one device
per vin" / "at most one enabled device globally" still behave correctly:

  1. `get_device_by_vin` no longer raises `MultipleResultsFound` when a vin has
     two devices — it deterministically returns the most-recently-active one.
  2. `get_device_id_by_token`'s global-token fallback excludes `kind='torque'`
     so adding a Torque source doesn't turn a previously-unambiguous
     single-WiCAN install into "ambiguous" global-token resolution.
"""

import itertools
from datetime import timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.livelink_service import LiveLinkService
from app.utils.datetime_utils import utc_now

# Module-level counter for unique identifiers across all tests in this file.
_SEQ = itertools.count()


async def _make_vehicle(db_session: AsyncSession) -> str:
    """Create a minimal user + vehicle, return the (unique) vin."""
    n = next(_SEQ)
    user = User(
        username=f"cardinality_user_{n}",
        email=f"cardinality_{n}@example.com",
        hashed_password="x",
        is_active=True,
        is_admin=False,
    )
    db_session.add(user)
    await db_session.flush()

    vin = f"CARDTEST{n:09d}"  # 17 chars
    vehicle = Vehicle(
        vin=vin,
        user_id=user.id,
        nickname=f"Cardinality Car {n}",
        vehicle_type="Car",
    )
    db_session.add(vehicle)
    await db_session.flush()
    return vin


@pytest.mark.asyncio
async def test_get_device_by_vin_returns_newest_when_two_devices_share_a_vin(
    db_session: AsyncSession,
):
    """WiCAN + Torque device sharing a vin: no raise, newer last_seen wins."""
    vin = await _make_vehicle(db_session)
    now = utc_now()

    wican = LiveLinkDevice(
        device_id=f"wc{next(_SEQ):010d}",
        vin=vin,
        kind="wican",
        enabled=True,
        last_seen=now - timedelta(hours=1),
    )
    torque = LiveLinkDevice(
        device_id=f"tq{next(_SEQ):010d}",
        vin=vin,
        kind="torque",
        enabled=True,
        last_seen=now,
    )
    db_session.add_all([wican, torque])
    await db_session.commit()

    device = await LiveLinkService(db_session).get_device_by_vin(vin)

    assert device is not None
    assert device.kind == "torque"
    assert device.device_id == torque.device_id


@pytest.mark.asyncio
async def test_get_device_by_vin_null_last_seen_sorts_last(db_session: AsyncSession):
    """nullslast(): a device that has never checked in never outranks one that has."""
    vin = await _make_vehicle(db_session)

    seen = LiveLinkDevice(
        device_id=f"sn{next(_SEQ):010d}",
        vin=vin,
        kind="wican",
        enabled=True,
        last_seen=utc_now(),
    )
    unseen = LiveLinkDevice(
        device_id=f"un{next(_SEQ):010d}",
        vin=vin,
        kind="torque",
        enabled=True,
        last_seen=None,
    )
    # Insertion order deliberately reversed vs. desired result — proves the
    # ordering comes from last_seen, not row/insert order.
    db_session.add_all([unseen, seen])
    await db_session.commit()

    device = await LiveLinkService(db_session).get_device_by_vin(vin)

    assert device is not None
    assert device.device_id == seen.device_id


@pytest.mark.asyncio
async def test_global_token_fallback_excludes_torque(db_session: AsyncSession):
    """One enabled WiCAN + one enabled Torque device: global fallback picks the WiCAN one."""
    # The test DB persists across the whole pytest session (see tests/conftest.py:
    # session-scoped engine), so earlier tests may have left other enabled
    # devices behind. Neutralize them so "exactly one enabled wican device" is
    # evaluated only against the two rows this test creates. Rows created by
    # tests that run *after* this one are unaffected (they set enabled=True
    # themselves later).
    await db_session.execute(update(LiveLinkDevice).values(enabled=False))
    await db_session.commit()

    vin = await _make_vehicle(db_session)
    wican = LiveLinkDevice(
        device_id=f"gw{next(_SEQ):010d}",
        vin=vin,
        kind="wican",
        enabled=True,
    )
    torque = LiveLinkDevice(
        device_id=f"gt{next(_SEQ):010d}",
        vin=vin,
        kind="torque",
        enabled=True,
    )
    db_session.add_all([wican, torque])
    await db_session.commit()

    device_id = await LiveLinkService(db_session).get_device_id_by_token(None)

    assert device_id == wican.device_id

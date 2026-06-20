"""Endpoint tests for track-aware firmware routes (Task 4).

Fixtures:
  - ``client`` / ``auth_headers`` — from tests/conftest.py (base conftest).
  - ``seed_cache`` — defined here; inserts a LiveLinkFirmwareCache row directly.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_firmware_cache import LiveLinkFirmwareCache
from app.utils.datetime_utils import utc_now


@pytest_asyncio.fixture
async def seed_cache(db_session: AsyncSession):
    """Return a coroutine-callable that inserts/replaces a firmware cache row."""
    from sqlalchemy import select

    async def _seed(track: str, version: str, tag: str) -> None:
        result = await db_session.execute(
            select(LiveLinkFirmwareCache).where(LiveLinkFirmwareCache.track == track)
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = LiveLinkFirmwareCache(track=track)
            db_session.add(row)
        row.latest_version = version
        row.latest_tag = tag
        row.release_url = f"https://example.com/{tag}"
        row.release_notes = None
        row.checked_at = utc_now()
        await db_session.commit()

    return _seed


@pytest.mark.asyncio
async def test_latest_defaults_to_pro(client: AsyncClient, auth_headers, seed_cache):
    """GET /firmware/latest with no ?track= returns the 'pro' cache row."""
    await seed_cache(track="pro", version="4.50", tag="v4.50p")
    await seed_cache(track="obd", version="4.21", tag="v4.21")

    r = await client.get("/api/livelink/firmware/latest", headers=auth_headers)

    assert r.status_code == 200
    body = r.json()
    assert body["firmware_track"] == "pro"
    assert body["latest_version"] == "4.50"


@pytest.mark.asyncio
async def test_latest_obd_track(client: AsyncClient, auth_headers, seed_cache):
    """GET /firmware/latest?track=obd returns the 'obd' cache row."""
    await seed_cache(track="obd", version="4.21", tag="v4.21")

    r = await client.get("/api/livelink/firmware/latest?track=obd", headers=auth_headers)

    assert r.status_code == 200
    assert r.json()["latest_version"] == "4.21"


@pytest.mark.asyncio
async def test_latest_invalid_track_422(client: AsyncClient, auth_headers):
    """GET /firmware/latest?track=bogus returns 422 (invalid enum value)."""
    r = await client.get("/api/livelink/firmware/latest?track=bogus", headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_check_returns_single_default_track(client: AsyncClient, auth_headers, monkeypatch):
    """POST /firmware/check refreshes both tracks and returns one FirmwareInfoResponse."""

    async def fake_check(self):
        return {"tracks": {"pro": {"latest_version": "4.50"}, "obd": {"latest_version": "4.21"}}}

    monkeypatch.setattr(
        "app.services.firmware_service.FirmwareService.check_firmware_updates", fake_check
    )

    # Also patch get_cached_firmware_info so it doesn't hit a cold DB after fake_check
    async def fake_cached(self, track: str = "pro"):
        data = {"pro": {"latest_version": "4.50"}, "obd": {"latest_version": "4.21"}}
        return {
            "latest_version": data[track]["latest_version"],
            "latest_tag": f"v{data[track]['latest_version']}{'p' if track == 'pro' else ''}",
            "release_url": None,
            "release_notes": None,
            "checked_at": utc_now(),
            "firmware_track": track,
        }

    monkeypatch.setattr(
        "app.services.firmware_service.FirmwareService.get_cached_firmware_info", fake_cached
    )

    r = await client.post("/api/livelink/firmware/check", headers=auth_headers)

    assert r.status_code == 200
    body = r.json()
    # Single FirmwareInfoResponse for the default (pro) track, not an aggregate.
    assert body["firmware_track"] == "pro"
    assert "tracks" not in body

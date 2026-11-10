"""Tests for multi-track firmware fetch, cache, and per-device comparison."""

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice
from app.services.firmware_service import FirmwareService

RELEASES = [
    {
        "tag_name": "v4.21",
        "name": "WiCAN-OBD v4.21",
        "prerelease": False,
        "draft": False,
        "html_url": "u/4.21",
        "body": "obd",
    },
    {
        "tag_name": "v4.50p",
        "name": "WiCAN-PRO v4.50",
        "prerelease": False,
        "draft": False,
        "html_url": "u/4.50p",
        "body": "pro",
    },
    {
        "tag_name": "v4.49p_beta-06",
        "name": "WiCAN-PRO v4.49 Beta-06",
        "prerelease": True,
        "draft": False,
        "html_url": "u/4.49b6",
        "body": "beta",
    },
    {
        "tag_name": "v4.48p",
        "name": "WiCAN-PRO v4.48",
        "prerelease": False,
        "draft": False,
        "html_url": "u/4.48p",
        "body": "pro old",
    },
]


class _FakeResp:
    def __init__(self, data):
        self._data = data
        self.headers = {}  # no Link header → single page

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


async def _make_device(
    session: AsyncSession, device_id: str, hw: str | None, fw: str
) -> LiveLinkDevice:
    """Insert a minimal LiveLinkDevice row for firmware tests."""
    device = LiveLinkDevice(
        device_id=device_id,
        hw_version=hw,
        fw_version=fw,
        vin=None,
    )
    session.add(device)
    await session.commit()
    await session.refresh(device)
    return device


@pytest.mark.asyncio
async def test_check_refreshes_both_tracks(db_session, monkeypatch):
    async def fake_get(self, url, **kwargs):
        return _FakeResp(RELEASES)

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)
    svc = FirmwareService(db_session)

    result = await svc.check_firmware_updates()

    assert result["tracks"]["obd"]["latest_version"] == "4.21"
    assert result["tracks"]["pro"]["latest_version"] == "4.50"  # beta excluded


@pytest.mark.asyncio
async def test_unflagged_pro_beta_does_not_pollute_obd_track(db_session, monkeypatch):
    # Regression (caught in prod): meatpi shipped v4.22p-beta — a PRO beta —
    # WITHOUT the prerelease flag and with a hyphen separator. It must NOT
    # land on the OBD track (which would offer OBD devices PRO firmware).
    # OBD must resolve to the real stable v4.21; PRO stays v4.50.
    releases = RELEASES + [
        {
            "tag_name": "v4.22p-beta",
            "name": "WiCAN-PRO v4.22 Beta",
            "prerelease": False,  # meatpi did NOT flag it
            "draft": False,
            "html_url": "u/4.22pbeta",
            "body": "pro beta, unflagged",
        },
    ]

    async def fake_get(self, url, **kwargs):
        return _FakeResp(releases)

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)
    svc = FirmwareService(db_session)

    await svc.check_firmware_updates()

    obd = await svc.get_cached_firmware_info("obd")
    pro = await svc.get_cached_firmware_info("pro")
    assert obd is not None and pro is not None
    assert obd["latest_version"] == "4.21"  # NOT 4.22
    assert pro["latest_version"] == "4.50"
    pro = await svc.get_cached_firmware_info("pro")
    obd = await svc.get_cached_firmware_info("obd")
    assert obd is not None and pro is not None
    assert pro["latest_version"] == "4.50"
    assert obd["latest_version"] == "4.21"


@pytest.mark.asyncio
async def test_device_compared_against_its_track(db_session, monkeypatch):
    async def fake_get(self, url, **kwargs):
        return _FakeResp(RELEASES)

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)
    svc = FirmwareService(db_session)
    await svc.check_firmware_updates()

    # PRO device on 4.48 → update to 4.50 available (NOT compared to OBD 4.21).
    await _make_device(db_session, "pro1", hw="WiCAN-OBD-PRO", fw="4.48")
    pro_status = await svc.check_device_firmware("pro1")
    assert pro_status["firmware_track"] == "pro"
    assert pro_status["latest_version"] == "4.50"
    assert pro_status["update_available"] is True

    # OBD device on 4.21 → up to date; never told to install PRO 4.50.
    await _make_device(db_session, "obd1", hw="WiCAN-OBD", fw="4.21")
    obd_status = await svc.check_device_firmware("obd1")
    assert obd_status["firmware_track"] == "obd"
    assert obd_status["latest_version"] == "4.21"
    assert obd_status["update_available"] is False


@pytest.mark.asyncio
async def test_unknown_hardware_surfaces_no_update(db_session, monkeypatch):
    async def fake_get(self, url, **kwargs):
        return _FakeResp(RELEASES)

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)
    svc = FirmwareService(db_session)
    await svc.check_firmware_updates()

    await _make_device(db_session, "x1", hw=None, fw="1.0")
    status = await svc.check_device_firmware("x1")
    assert status["firmware_track"] is None
    assert status["update_available"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("blank", ["", "   "], ids=["empty", "spaces"])
async def test_a_blank_firmware_version_never_needs_an_update(db_session, monkeypatch, blank):
    """A device stored with a blank fw_version never said what it runs. A
    blank sorted below every release, so it "needed" each one. Spaces are
    blank too: ingest only turns them into None from H4 on, so older rows
    still hold them. The per-device check has to agree with the list."""

    async def fake_get(self, url, **kwargs):
        return _FakeResp(RELEASES)

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)
    svc = FirmwareService(db_session)
    await svc.check_firmware_updates()

    device_id = "h4blankfw"
    await _make_device(db_session, device_id, hw="WiCAN-OBD-PRO", fw="4.48")
    try:
        # With a real version the same row does need 4.50, so the blank is
        # the only thing keeping it off the list below.
        assert device_id in [d["device_id"] for d in await svc.get_devices_needing_update()]
        assert (await svc.check_device_firmware(device_id))["update_available"] is True

        await db_session.execute(
            text("UPDATE livelink_devices SET fw_version = :blank WHERE device_id = :device_id"),
            {"blank": blank, "device_id": device_id},
        )
        await db_session.commit()
        db_session.expire_all()

        needing = await svc.get_devices_needing_update()
        assert device_id not in [d["device_id"] for d in needing]
        check = await svc.check_device_firmware(device_id)
        assert check["update_available"] is None
        assert check["compatible"] is None
    finally:
        await db_session.rollback()
        await db_session.execute(
            delete(LiveLinkDevice).where(LiveLinkDevice.device_id == device_id)
        )
        await db_session.commit()


# ---------------------------------------------------------------------------
# Pagination: _fetch_releases follows the Link: rel="next" header
# ---------------------------------------------------------------------------

PAGE1 = [
    {
        "tag_name": "v4.21",
        "name": "WiCAN-OBD v4.21",
        "prerelease": False,
        "draft": False,
        "html_url": "u/4.21",
        "body": "obd stable",
    },
]

PAGE2 = [
    {
        "tag_name": "v4.50p",
        "name": "WiCAN-PRO v4.50",
        "prerelease": False,
        "draft": False,
        "html_url": "u/4.50p",
        "body": "pro stable",
    },
]


class _FakeRespPaged:
    """Fake HTTP response that carries a Link header on the first page only."""

    def __init__(self, data, *, link: str = ""):
        self._data = data
        self.headers = {"link": link} if link else {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


@pytest.mark.asyncio
async def test_fetch_releases_follows_link_header(db_session, monkeypatch):
    """_fetch_releases paginates via the Link: rel="next" header.

    Page 1 contains only an OBD stable release; the PRO stable release is on
    page 2. After check_firmware_updates() both ``obd`` and ``pro`` cache rows
    must be populated.
    """
    calls: list[str] = []

    async def fake_get(self, url, **kwargs):
        calls.append(url)
        if "page=2" in url:
            return _FakeRespPaged(PAGE2)
        # Page 1: return OBD release + a Link pointing to page 2
        return _FakeRespPaged(
            PAGE1,
            link='<https://api.github.com/repos/meatpiHQ/wican-fw/releases?page=2>; rel="next"',
        )

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)
    svc = FirmwareService(db_session)

    result = await svc.check_firmware_updates()

    # Both tracks resolved across two pages
    assert "obd" in result["tracks"], "obd track missing from result"
    assert "pro" in result["tracks"], "pro track missing from result"
    assert result["tracks"]["obd"]["latest_version"] == "4.21"
    assert result["tracks"]["pro"]["latest_version"] == "4.50"

    # Cache rows written for both tracks
    obd_cache = await svc.get_cached_firmware_info("obd")
    pro_cache = await svc.get_cached_firmware_info("pro")
    assert obd_cache is not None and obd_cache["latest_version"] == "4.21"
    assert pro_cache is not None and pro_cache["latest_version"] == "4.50"

    # Two HTTP calls were made (page 1 then page 2)
    assert len(calls) == 2, f"Expected 2 HTTP calls, got {len(calls)}: {calls}"

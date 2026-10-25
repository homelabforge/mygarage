"""
Integration tests for SD-card backfill admin endpoints.

Tests admin-only SD config + backfill trigger routes, including SSRF validation.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.livelink_device import LiveLinkDevice

# LiveLink's master switch gates the ingest pipeline and SD backfill, and it is
# off by default. Explicit, not inherited from whatever an earlier test left in
# the shared database. `test_vehicle` seeds the VIN every device here links
# to; without it the file only passed after some other test had made one.
pytestmark = pytest.mark.usefixtures("livelink_enabled", "test_vehicle")


@pytest.mark.integration
@pytest.mark.asyncio
class TestSdConfigAdmin:
    """Test PUT /api/livelink/devices/{device_id}/sd-config (admin-only)."""

    async def test_set_sd_config_rejects_public_address(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        """SSRF guard: a public IP (8.8.8.8) must be rejected with 422."""
        device = LiveLinkDevice(device_id="sdtest000001", vin="1HGBH41JXMN109186")
        db_session.add(device)
        await db_session.commit()
        await db_session.refresh(device)

        response = await client.put(
            f"/api/livelink/devices/{device.device_id}/sd-config",
            headers=auth_headers,
            json={"device_address": "8.8.8.8", "sd_backfill_enabled": True},
        )
        assert response.status_code == 422

    async def test_set_sd_config_accepts_private_address(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        """A private LAN address (10.x.x.x) must be accepted with 200."""
        device = LiveLinkDevice(device_id="sdtest000002", vin="1HGBH41JXMN109186")
        db_session.add(device)
        await db_session.commit()
        await db_session.refresh(device)

        with patch("app.routes.livelink_admin.LiveLinkService") as mock_svc_cls:
            mock_svc = MagicMock()
            mock_svc.is_private_address = MagicMock(return_value=True)
            mock_svc.update_device_address = AsyncMock(return_value=None)
            mock_svc_cls.return_value = mock_svc

            response = await client.put(
                f"/api/livelink/devices/{device.device_id}/sd-config",
                headers=auth_headers,
                json={"device_address": "10.10.20.244", "sd_backfill_enabled": True},
            )

        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"

    async def test_set_sd_config_refuses_a_source_without_sd_backfill(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        """Fable F5-1: a generic device has no SD card to pull, so a stray
        address can't be saved for it. Main wrote it blind (200)."""
        device = LiveLinkDevice(
            device_id="sdtest000010", vin="1HGBH41JXMN109186", kind="generic_mqtt"
        )
        db_session.add(device)
        await db_session.commit()

        response = await client.put(
            f"/api/livelink/devices/{device.device_id}/sd-config",
            headers=auth_headers,
            json={"device_address": "10.10.20.244", "sd_backfill_enabled": True},
        )

        assert response.status_code == 422
        db_session.expire_all()
        stored = (
            await db_session.execute(
                select(LiveLinkDevice).where(LiveLinkDevice.device_id == "sdtest000010")
            )
        ).scalar_one()
        assert stored.device_address is None
        assert stored.sd_backfill_enabled is False

    async def test_set_sd_config_unknown_device_is_404(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Main ran a blind UPDATE that matched nothing and answered 200."""
        response = await client.put(
            "/api/livelink/devices/sdtestmissing1/sd-config",
            headers=auth_headers,
            json={"device_address": "10.10.20.244", "sd_backfill_enabled": True},
        )
        assert response.status_code == 404

    async def test_set_sd_config_saves_for_a_wican(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        """Regression guard: the real service (the test above mocks it whole)
        still saves a WiCAN's address."""
        device = LiveLinkDevice(device_id="sdtest000011", vin="1HGBH41JXMN109186", kind="wican")
        db_session.add(device)
        await db_session.commit()

        response = await client.put(
            f"/api/livelink/devices/{device.device_id}/sd-config",
            headers=auth_headers,
            json={"device_address": "10.10.20.244", "sd_backfill_enabled": True},
        )

        assert response.status_code == 200
        db_session.expire_all()
        stored = (
            await db_session.execute(
                select(LiveLinkDevice).where(LiveLinkDevice.device_id == "sdtest000011")
            )
        ).scalar_one()
        assert stored.device_address == "10.10.20.244"
        assert stored.sd_backfill_enabled is True

    async def test_set_sd_config_unauthorized(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Unauthenticated request must be rejected with 401."""
        device = LiveLinkDevice(device_id="sdtest000003", vin="1HGBH41JXMN109186")
        db_session.add(device)
        await db_session.commit()
        await db_session.refresh(device)

        response = await client.put(
            f"/api/livelink/devices/{device.device_id}/sd-config",
            json={"device_address": "192.168.1.50", "sd_backfill_enabled": True},
        )
        assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
class TestBackfillTriggerAdmin:
    """Test POST /api/livelink/devices/{device_id}/backfill (admin-only)."""

    async def test_backfill_trigger_requires_admin(
        self,
        client: AsyncClient,
        non_admin_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        """Non-admin authenticated user must get 401 or 403."""
        device = LiveLinkDevice(device_id="sdtest000004", vin="1HGBH41JXMN109186")
        db_session.add(device)
        await db_session.commit()
        await db_session.refresh(device)

        response = await client.post(
            f"/api/livelink/devices/{device.device_id}/backfill",
            headers=non_admin_headers,
        )
        assert response.status_code in (401, 403)

    async def test_backfill_trigger_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        """Admin can trigger a backfill and receives a BackfillResultResponse."""
        from app.services.sd_backfill_service import BackfillResult

        device = LiveLinkDevice(device_id="sdtest000005", vin="1HGBH41JXMN109186")
        db_session.add(device)
        await db_session.commit()
        await db_session.refresh(device)

        fake_result = BackfillResult(files_seen=3, rows_ingested=42, rows_skipped=1, errors=[])

        with patch("app.routes.livelink_admin.SdBackfillService") as mock_svc_cls:
            mock_svc = MagicMock()
            mock_svc.backfill_device = AsyncMock(return_value=fake_result)
            mock_svc_cls.return_value = mock_svc

            response = await client.post(
                f"/api/livelink/devices/{device.device_id}/backfill",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["files_seen"] == 3
        assert data["rows_ingested"] == 42
        assert data["rows_skipped"] == 1
        assert data["errors"] == []

    @pytest.mark.asyncio
    async def test_backfill_trigger_is_refused_while_livelink_is_off(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        """409, and the service is never asked: "pull now" doing nothing
        silently would look like a broken dongle."""
        from app.models.settings import Setting

        device = LiveLinkDevice(device_id="sdtest000009", vin="1HGBH41JXMN109186")
        db_session.add(device)
        row = await db_session.get(Setting, "livelink_enabled")
        row.value = "false"  # the module's fixture put it on, and puts it back
        await db_session.commit()

        with patch("app.routes.livelink_admin.SdBackfillService") as mock_svc_cls:
            response = await client.post(
                f"/api/livelink/devices/{device.device_id}/backfill",
                headers=auth_headers,
            )

        assert response.status_code == 409
        mock_svc_cls.assert_not_called()

    async def test_backfill_trigger_unauthenticated(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Unauthenticated request must be rejected with 401."""
        device = LiveLinkDevice(device_id="sdtest000006", vin="1HGBH41JXMN109186")
        db_session.add(device)
        await db_session.commit()
        await db_session.refresh(device)

        response = await client.post(
            f"/api/livelink/devices/{device.device_id}/backfill",
        )
        assert response.status_code == 401

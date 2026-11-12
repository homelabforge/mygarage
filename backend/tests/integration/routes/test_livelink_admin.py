"""
Integration tests for LiveLink admin routes.

Tests settings, device management, parameters, firmware, and MQTT endpoints.
"""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Setting
from tests._keep_rows import Keep


@pytest.mark.integration
@pytest.mark.asyncio
class TestLiveLinkSettings:
    """Test LiveLink settings endpoints."""

    async def test_get_settings_unauthorized(self, client: AsyncClient):
        """Test getting settings without authentication."""
        response = await client.get("/api/livelink/settings")
        assert response.status_code == 401

    async def test_get_settings_success(self, client: AsyncClient, auth_headers):
        """Test getting LiveLink settings."""
        response = await client.get("/api/livelink/settings", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        # Check expected fields exist
        assert "enabled" in data
        assert "has_global_token" in data
        assert "ingestion_url" in data
        assert "telemetry_retention_days" in data

    async def test_update_settings_unauthorized(self, client: AsyncClient):
        """Test updating settings without authentication."""
        response = await client.put(
            "/api/livelink/settings",
            json={"enabled": True},
        )
        assert response.status_code == 401

    async def test_update_settings_success(self, client: AsyncClient, auth_headers):
        """Test updating LiveLink settings."""
        update_data = {
            "enabled": True,
            "telemetry_retention_days": 30,
            "session_timeout_minutes": 10,
        }

        response = await client.put(
            "/api/livelink/settings",
            headers=auth_headers,
            json=update_data,
        )

        assert response.status_code == 200
        data = response.json()
        assert "enabled" in data


@pytest.mark.integration
@pytest.mark.asyncio
class TestLiveLinkToken:
    """Test LiveLink token management endpoints."""

    async def test_regenerate_token_unauthorized(self, client: AsyncClient):
        """Test token regeneration without authentication."""
        response = await client.post("/api/livelink/token")
        assert response.status_code == 401

    async def test_regenerate_token_success(self, client: AsyncClient, auth_headers):
        """Test generating a new global token."""
        with patch("app.routes.livelink_admin.LiveLinkService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.generate_global_token = AsyncMock(return_value="new_test_token_12345")
            mock_service_class.return_value = mock_service

            response = await client.post("/api/livelink/token", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["token"] == "new_test_token_12345"
        assert "expires_at" in data  # Should be None for global tokens


@pytest.mark.integration
@pytest.mark.asyncio
class TestLiveLinkDevices:
    """Test LiveLink device management endpoints."""

    async def test_list_devices_unauthorized(self, client: AsyncClient):
        """Test listing devices without authentication."""
        response = await client.get("/api/livelink/devices")
        assert response.status_code == 401

    async def test_list_devices_empty(self, client: AsyncClient, auth_headers):
        """Test listing devices when none exist."""
        with patch("app.routes.livelink_admin.LiveLinkService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.list_devices = AsyncMock(return_value=[])
            # The route asks which devices report telemetry but nothing readable
            # as movement, so the settings page can name them. Stubbed because
            # the whole service is replaced here; the predicate itself is
            # covered in tests/unit/services/test_movement_unreadable_devices.py.
            mock_service.movement_unreadable_device_ids = AsyncMock(return_value=set())
            mock_service_class.return_value = mock_service

            response = await client.get("/api/livelink/devices", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["devices"] == []
        assert data["total"] == 0
        assert data["online_count"] == 0

    async def test_get_device_not_found(self, client: AsyncClient, auth_headers):
        """Test getting a non-existent device."""
        with patch("app.routes.livelink_admin.LiveLinkService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_device_by_id = AsyncMock(return_value=None)
            mock_service_class.return_value = mock_service

            response = await client.get(
                "/api/livelink/devices/nonexistent_device",
                headers=auth_headers,
            )

        assert response.status_code == 404

    async def test_delete_device_not_found(self, client: AsyncClient, auth_headers):
        """Test deleting a non-existent device."""
        with patch("app.routes.livelink_admin.LiveLinkService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_device_by_id = AsyncMock(return_value=None)
            mock_service.delete_device = AsyncMock(return_value=False)
            mock_service_class.return_value = mock_service

            response = await client.delete(
                "/api/livelink/devices/nonexistent",
                headers=auth_headers,
            )

        assert response.status_code == 404

    async def test_delete_device_success(self, client: AsyncClient, auth_headers):
        """Test successfully deleting a device."""
        with patch("app.routes.livelink_admin.LiveLinkService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_device_by_id = AsyncMock(return_value=MagicMock(vin=None))
            mock_service.delete_device = AsyncMock(return_value=True)
            mock_service_class.return_value = mock_service

            response = await client.delete(
                "/api/livelink/devices/device_to_delete",
                headers=auth_headers,
            )

        assert response.status_code == 204


@pytest.mark.integration
@pytest.mark.asyncio
class TestLiveLinkDeviceTokens:
    """Test device token management endpoints."""

    async def test_generate_device_token_not_found(self, client: AsyncClient, auth_headers):
        """Test generating token for non-existent device."""
        with patch("app.routes.livelink_admin.LiveLinkService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_device_by_id = AsyncMock(return_value=None)
            mock_service.generate_device_token = AsyncMock(return_value=None)
            mock_service_class.return_value = mock_service

            response = await client.post(
                "/api/livelink/devices/nonexistent/token",
                headers=auth_headers,
            )

        assert response.status_code == 404

    async def test_generate_device_token_success(self, client: AsyncClient, auth_headers):
        """Test generating per-device token."""
        with patch("app.routes.livelink_admin.LiveLinkService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_device_by_id = AsyncMock(return_value=MagicMock(vin=None))
            mock_service.generate_device_token = AsyncMock(return_value="device_token_xyz")
            mock_service_class.return_value = mock_service

            response = await client.post(
                "/api/livelink/devices/test_device/token",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["token"] == "device_token_xyz"

    async def test_revoke_device_token_not_found(self, client: AsyncClient, auth_headers):
        """Test revoking token for non-existent device."""
        with patch("app.routes.livelink_admin.LiveLinkService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_device_by_id = AsyncMock(return_value=None)
            mock_service.revoke_device_token = AsyncMock(return_value=False)
            mock_service_class.return_value = mock_service

            response = await client.delete(
                "/api/livelink/devices/nonexistent/token",
                headers=auth_headers,
            )

        assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
class TestLiveLinkParameters:
    """Test LiveLink parameter management endpoints."""

    async def test_list_parameters_unauthorized(self, client: AsyncClient):
        """Test listing parameters without authentication."""
        response = await client.get("/api/livelink/parameters")
        assert response.status_code == 401

    async def test_get_parameter_not_found(self, client: AsyncClient, auth_headers):
        """Test getting a non-existent parameter."""
        with patch("app.routes.livelink_admin.TelemetryService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_parameter = AsyncMock(return_value=None)
            mock_service_class.return_value = mock_service

            response = await client.get(
                "/api/livelink/parameters/NONEXISTENT_PARAM",
                headers=auth_headers,
            )

        assert response.status_code == 404


_LENGTH_KEY = "PARAMLEN_TEST"


@pytest_asyncio.fixture
async def length_param(db_session: AsyncSession) -> AsyncIterator[str]:
    """One parameter row to rename, gone again after the test."""
    from app.models.livelink_parameter import LiveLinkParameter

    async def _wipe() -> None:
        await db_session.execute(
            delete(LiveLinkParameter).where(LiveLinkParameter.param_key == _LENGTH_KEY)
        )
        await db_session.commit()

    await _wipe()
    db_session.add(LiveLinkParameter(param_key=_LENGTH_KEY))
    await db_session.commit()
    yield _LENGTH_KEY
    await _wipe()


# The column widths: display_name is String(100), category and icon String(50).
# PostgreSQL refuses a longer value at commit (a 500); SQLite stores it whole.
_FIELD_WIDTHS = [("display_name", 100), ("category", 50), ("icon", 50)]


@pytest.mark.integration
@pytest.mark.asyncio
class TestParameterTextLengths:
    """PUT /parameters/{key} holds the free-text fields to their column widths."""

    @pytest.mark.parametrize(("field", "width"), _FIELD_WIDTHS)
    async def test_one_past_the_column_is_a_422(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        length_param: str,
        field: str,
        width: int,
    ) -> None:
        response = await client.put(
            f"/api/livelink/parameters/{length_param}",
            headers=auth_headers,
            json={field: "x" * (width + 1)},
        )

        assert response.status_code == 422, response.text
        assert await _stored(db_session, field) is None

    @pytest.mark.parametrize(("field", "width"), _FIELD_WIDTHS)
    async def test_exactly_the_column_is_stored(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        length_param: str,
        field: str,
        width: int,
    ) -> None:
        response = await client.put(
            f"/api/livelink/parameters/{length_param}",
            headers=auth_headers,
            json={field: "x" * width},
        )

        assert response.status_code == 200, response.text
        assert response.json()[field] == "x" * width
        assert await _stored(db_session, field) == "x" * width


async def _stored(db: AsyncSession, field: str) -> str | None:
    """The test parameter's column as committed, not as the session last saw it."""
    from app.models.livelink_parameter import LiveLinkParameter

    db.expire_all()
    return (
        await db.execute(
            select(getattr(LiveLinkParameter, field)).where(
                LiveLinkParameter.param_key == _LENGTH_KEY
            )
        )
    ).scalar_one()


@pytest.mark.parametrize(("field", "width"), [("display_name", 100), ("category", 50)])
def test_the_create_schema_holds_the_same_widths(field: str, width: int) -> None:
    """Nothing posts it yet, but it shouldn't be the one shape that lets a long name through."""
    from app.schemas.livelink import LiveLinkParameterCreate

    assert getattr(LiveLinkParameterCreate(param_key="K", **{field: "x" * width}), field) == (
        "x" * width
    )
    with pytest.raises(ValidationError):
        LiveLinkParameterCreate(param_key="K", **{field: "x" * (width + 1)})


@pytest.mark.integration
@pytest.mark.asyncio
class TestLiveLinkFirmware:
    """Test LiveLink firmware endpoints."""

    async def test_get_latest_firmware_unauthorized(self, client: AsyncClient):
        """Test getting firmware info without authentication."""
        response = await client.get("/api/livelink/firmware/latest")
        assert response.status_code == 401

    async def test_get_latest_firmware_success(self, client: AsyncClient, auth_headers):
        """Test getting latest firmware info."""
        with patch("app.routes.livelink_admin.FirmwareService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_cached_firmware_info = AsyncMock(
                return_value={
                    "latest_version": "2.5.0",
                    "latest_tag": "v2.5.0",
                    "release_url": "https://github.com/meatpiHQ/wican-fw/releases/tag/v2.5.0",
                    "release_notes": "Bug fixes and improvements",
                    "checked_at": "2024-01-15T10:30:00Z",
                }
            )
            mock_service_class.return_value = mock_service

            response = await client.get("/api/livelink/firmware/latest", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["latest_version"] == "2.5.0"
        assert "release_url" in data

    async def test_trigger_firmware_check(self, client: AsyncClient, auth_headers):
        """Test triggering firmware check."""
        with patch("app.routes.livelink_admin.FirmwareService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.check_firmware_updates = AsyncMock(return_value=None)
            mock_service.get_cached_firmware_info = AsyncMock(
                return_value={
                    "latest_version": "2.6.0",
                    "latest_tag": "v2.6.0",
                    "release_url": "https://github.com/meatpiHQ/wican-fw/releases/tag/v2.6.0",
                    "release_notes": "New features",
                    "firmware_track": "pro",
                }
            )
            mock_service_class.return_value = mock_service

            response = await client.post("/api/livelink/firmware/check", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["latest_version"] == "2.6.0"


@pytest.mark.integration
@pytest.mark.asyncio
class TestLiveLinkDTCDefinitions:
    """Test DTC definition lookup endpoints."""

    async def test_lookup_dtc_unauthorized(self, client: AsyncClient):
        """Test DTC lookup without authentication."""
        response = await client.get("/api/livelink/dtc-definitions/P0301")
        assert response.status_code == 401

    async def test_lookup_dtc_not_found(self, client: AsyncClient, auth_headers):
        """Test lookup for unknown DTC code."""
        with patch("app.routes.livelink_admin.DTCService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.lookup_dtc = AsyncMock(return_value=None)
            mock_service_class.return_value = mock_service

            response = await client.get(
                "/api/livelink/dtc-definitions/XXXXX",
                headers=auth_headers,
            )

        assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
class TestLiveLinkMQTT:
    """Test MQTT settings endpoints."""

    async def test_get_mqtt_settings_unauthorized(self, client: AsyncClient):
        """Test getting MQTT settings without authentication."""
        response = await client.get("/api/livelink/mqtt/settings")
        assert response.status_code == 401

    async def test_get_mqtt_settings_success(self, client: AsyncClient, auth_headers):
        """Test getting MQTT settings."""
        response = await client.get("/api/livelink/mqtt/settings", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "enabled" in data
        assert "broker_host" in data
        assert "broker_port" in data
        assert "topic_prefix" in data
        assert "use_tls" in data

    async def test_a_null_broker_host_or_username_reads_as_blank(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        keep_rows: Keep,
    ) -> None:
        # Setting.value stores None as is (a restore can bring one back).
        keys = ["livelink_mqtt_broker_host", "livelink_mqtt_username"]
        await keep_rows(*keys)
        await db_session.execute(delete(Setting).where(Setting.key.in_(keys)))
        for key in keys:
            db_session.add(Setting(key=key, value=None))
        await db_session.commit()

        response = await client.get("/api/livelink/mqtt/settings", headers=auth_headers)

        assert response.status_code == 200, response.text
        assert response.json()["broker_host"] == ""
        assert response.json()["username"] == ""

    async def test_update_mqtt_settings(self, client: AsyncClient, auth_headers):
        """Test updating MQTT settings."""
        update_data = {
            "enabled": True,
            "broker_host": "mqtt.example.com",
            "broker_port": 1883,
            "topic_prefix": "wican",
        }

        response = await client.put(
            "/api/livelink/mqtt/settings",
            headers=auth_headers,
            json=update_data,
        )

        assert response.status_code == 200
        data = response.json()
        assert "enabled" in data

    async def test_get_mqtt_status(self, client: AsyncClient, auth_headers):
        """Test getting MQTT subscriber status."""
        response = await client.get("/api/livelink/mqtt/status", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "running" in data
        # The actual field may be 'connection_status' instead of 'connected'
        assert "connection_status" in data or "connected" in data

    async def test_test_mqtt_connection(self, client: AsyncClient, auth_headers):
        """Test MQTT connection test endpoint."""
        response = await client.post("/api/livelink/mqtt/test", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert "message" in data
        # Will fail if no broker configured or aiomqtt not installed
        assert data["success"] is False

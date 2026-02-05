"""
Integration tests for vehicle-specific LiveLink routes.

Tests status, telemetry, sessions, DTCs, and export endpoints.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestVehicleLiveLinkStatus:
    """Test vehicle LiveLink status endpoint."""

    async def test_get_status_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test getting status without authentication."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}/livelink/status")
        assert response.status_code == 401

    async def test_get_status_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test getting status for non-existent vehicle."""
        response = await client.get(
            "/api/vehicles/NONEXISTENT12345VN/livelink/status",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_get_status_no_device(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test getting status when no device is linked."""
        with (
            patch("app.routes.livelink_vehicle.LiveLinkService") as mock_livelink_class,
            patch("app.routes.livelink_vehicle.TelemetryService") as mock_telemetry_class,
            patch("app.routes.livelink_vehicle.SessionService") as mock_session_class,
        ):
            mock_livelink = MagicMock()
            mock_livelink.get_device_by_vin = AsyncMock(return_value=None)
            mock_livelink_class.return_value = mock_livelink

            mock_telemetry = MagicMock()
            mock_telemetry.get_latest_values = AsyncMock(return_value=[])
            mock_telemetry.get_all_parameters = AsyncMock(return_value={})
            mock_telemetry_class.return_value = mock_telemetry

            mock_session = MagicMock()
            mock_session_class.return_value = mock_session

            response = await client.get(
                f"/api/vehicles/{test_vehicle['vin']}/livelink/status",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["vin"] == test_vehicle["vin"]
        assert data["device_id"] is None
        assert data["device_status"] == "offline"


@pytest.mark.integration
@pytest.mark.asyncio
class TestVehicleTelemetry:
    """Test vehicle telemetry query endpoint."""

    async def test_get_telemetry_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test getting telemetry without authentication."""
        now = datetime.now(UTC)
        start = now - timedelta(hours=1)
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/livelink/telemetry",
            params={"start": start.isoformat(), "end": now.isoformat()},
        )
        assert response.status_code == 401

    async def test_get_telemetry_missing_params(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test getting telemetry without required parameters."""
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/livelink/telemetry",
            headers=auth_headers,
        )
        # Missing start/end parameters
        assert response.status_code == 422

    async def test_get_telemetry_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test getting telemetry for non-existent vehicle."""
        now = datetime.now(UTC)
        start = now - timedelta(hours=1)
        response = await client.get(
            "/api/vehicles/NONEXISTENT12345VN/livelink/telemetry",
            headers=auth_headers,
            params={"start": start.isoformat(), "end": now.isoformat()},
        )
        assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
class TestVehicleSessions:
    """Test vehicle drive session endpoints."""

    async def test_list_sessions_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test listing sessions without authentication."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}/livelink/sessions")
        assert response.status_code == 401

    async def test_list_sessions_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test listing sessions for non-existent vehicle."""
        response = await client.get(
            "/api/vehicles/NONEXISTENT12345VN/livelink/sessions",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_list_sessions_empty(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test listing sessions when none exist."""
        with patch("app.routes.livelink_vehicle.SessionService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_vehicle_sessions = AsyncMock(return_value=[])
            mock_service.get_session_count = AsyncMock(return_value=0)
            mock_service_class.return_value = mock_service

            response = await client.get(
                f"/api/vehicles/{test_vehicle['vin']}/livelink/sessions",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["sessions"] == []
        assert data["total"] == 0

    async def test_get_session_detail_not_found(
        self, client: AsyncClient, auth_headers, test_vehicle
    ):
        """Test getting non-existent session."""
        with patch("app.routes.livelink_vehicle.SessionService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_session = AsyncMock(return_value=None)
            mock_service_class.return_value = mock_service

            response = await client.get(
                f"/api/vehicles/{test_vehicle['vin']}/livelink/sessions/99999",
                headers=auth_headers,
            )

        assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
class TestVehicleDTCs:
    """Test vehicle DTC endpoints."""

    async def test_list_dtcs_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test listing DTCs without authentication."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}/livelink/dtcs")
        assert response.status_code == 401

    async def test_list_dtcs_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test listing DTCs for non-existent vehicle."""
        response = await client.get(
            "/api/vehicles/NONEXISTENT12345VN/livelink/dtcs",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_list_dtcs_empty(self, client: AsyncClient, auth_headers, test_vehicle):
        """Test listing DTCs when none exist."""
        with patch("app.routes.livelink_vehicle.DTCService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_active_dtcs = AsyncMock(return_value=[])
            mock_service.get_dtc_counts = AsyncMock(return_value={"active": 0, "critical": 0})
            mock_service_class.return_value = mock_service

            response = await client.get(
                f"/api/vehicles/{test_vehicle['vin']}/livelink/dtcs",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["dtcs"] == []
        assert data["active_count"] == 0


@pytest.mark.integration
@pytest.mark.asyncio
class TestVehicleExport:
    """Test vehicle data export endpoints."""

    async def test_export_telemetry_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test exporting telemetry without authentication."""
        now = datetime.now(UTC)
        start = now - timedelta(hours=1)
        response = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/livelink/export/telemetry",
            params={"start": start.isoformat(), "end": now.isoformat()},
        )
        assert response.status_code == 401

    async def test_export_telemetry_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test exporting telemetry for non-existent vehicle."""
        now = datetime.now(UTC)
        start = now - timedelta(hours=1)
        response = await client.get(
            "/api/vehicles/NONEXISTENT12345VN/livelink/export/telemetry",
            headers=auth_headers,
            params={"start": start.isoformat(), "end": now.isoformat()},
        )
        assert response.status_code == 404

    async def test_export_sessions_unauthorized(self, client: AsyncClient, test_vehicle):
        """Test exporting sessions without authentication."""
        response = await client.get(f"/api/vehicles/{test_vehicle['vin']}/livelink/export/sessions")
        assert response.status_code == 401

    async def test_export_sessions_vehicle_not_found(self, client: AsyncClient, auth_headers):
        """Test exporting sessions for non-existent vehicle."""
        response = await client.get(
            "/api/vehicles/NONEXISTENT12345VN/livelink/export/sessions",
            headers=auth_headers,
        )
        assert response.status_code == 404

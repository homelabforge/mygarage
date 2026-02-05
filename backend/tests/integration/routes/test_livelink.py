"""
Integration tests for LiveLink ingestion routes.

Tests the WiCAN device telemetry ingestion endpoint.
Note: The /ingest endpoint uses token-based auth (not JWT), so these tests
verify the token validation flow.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestLiveLinkIngest:
    """Test LiveLink ingestion endpoint."""

    # -------------------------------------------------------------------------
    # Disabled LiveLink tests
    # -------------------------------------------------------------------------

    async def test_ingest_returns_disabled_when_livelink_off(self, client: AsyncClient):
        """Test ingestion returns disabled status when LiveLink is disabled."""
        payload = {
            "autopid_data": {"ENGINE_RPM": 1500},
            "config": {},
            "status": {
                "device_id": "test_device_123",
                "hw_version": "1.0",
                "fw_version": "1.0.0",
            },
        }

        # Mock to pass auth but have LiveLink disabled
        with (
            patch(
                "app.routes.livelink.validate_livelink_token", new_callable=AsyncMock
            ) as mock_validate,
            patch("app.routes.livelink.LiveLinkService") as mock_service_class,
        ):
            mock_validate.return_value = True
            mock_service = MagicMock()
            mock_service.is_enabled = AsyncMock(return_value=False)
            mock_service_class.return_value = mock_service

            response = await client.post(
                "/api/v1/livelink/ingest",
                json=payload,
                headers={"Authorization": "Bearer valid_token"},
            )

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "disabled"

    # -------------------------------------------------------------------------
    # Payload validation tests
    # -------------------------------------------------------------------------

    async def test_ingest_empty_payload_fails_validation(self, client: AsyncClient):
        """Test that empty payload fails validation."""
        response = await client.post(
            "/api/v1/livelink/ingest",
            json={},
            headers={"Authorization": "Bearer token"},
        )
        # Should fail Pydantic validation - autopid_data is required
        assert response.status_code == 422

    async def test_ingest_invalid_autopid_data_type(self, client: AsyncClient):
        """Test that invalid autopid_data type fails validation."""
        payload = {
            "autopid_data": "not_a_dict",  # Should be dict
            "config": {},
        }

        response = await client.post(
            "/api/v1/livelink/ingest",
            json=payload,
            headers={"Authorization": "Bearer token"},
        )
        assert response.status_code == 422

    async def test_ingest_valid_minimal_payload(self, client: AsyncClient):
        """Test that minimal valid payload is accepted."""
        payload = {
            "autopid_data": {},  # Empty but valid dict
            "config": {},
            "status": {
                "device_id": "test12345678",
                "hw_version": "1.0",
                "fw_version": "1.0.0",
            },
        }

        # Mock auth and service
        with (
            patch(
                "app.routes.livelink.validate_livelink_token", new_callable=AsyncMock
            ) as mock_validate,
            patch("app.routes.livelink.LiveLinkService") as mock_service_class,
        ):
            mock_validate.return_value = True
            mock_service = MagicMock()
            mock_service.is_enabled = AsyncMock(return_value=False)
            mock_service_class.return_value = mock_service

            response = await client.post(
                "/api/v1/livelink/ingest",
                json=payload,
                headers={"Authorization": "Bearer test_token"},
            )

        assert response.status_code == 202

    async def test_ingest_with_telemetry_data(self, client: AsyncClient):
        """Test payload with telemetry data."""
        payload = {
            "autopid_data": {
                "ENGINE_RPM": 2500,
                "VEHICLE_SPEED": 65,
                "COOLANT_TEMP": 92,
            },
            "config": {
                "ENGINE_RPM": {"unit": "rpm", "class": "engine"},
                "VEHICLE_SPEED": {"unit": "km/h", "class": "speed"},
                "COOLANT_TEMP": {"unit": "C", "class": "temperature"},
            },
            "status": {
                "device_id": "test12345678",
                "hw_version": "2.0",
                "fw_version": "2.5.0",
                "sta_ip": "192.168.1.100",
                "rssi": -55,
                "battery_voltage": 12.8,
                "ecu_status": "online",
            },
        }

        with (
            patch(
                "app.routes.livelink.validate_livelink_token", new_callable=AsyncMock
            ) as mock_validate,
            patch("app.routes.livelink.LiveLinkService") as mock_service_class,
        ):
            mock_validate.return_value = True
            mock_service = MagicMock()
            mock_service.is_enabled = AsyncMock(return_value=False)
            mock_service_class.return_value = mock_service

            response = await client.post(
                "/api/v1/livelink/ingest",
                json=payload,
                headers={"Authorization": "Bearer test_token"},
            )

        assert response.status_code == 202


@pytest.mark.integration
@pytest.mark.asyncio
class TestLiveLinkTokenValidation:
    """Test LiveLink token validation logic."""

    async def test_validate_token_no_header(self):
        """Test validation fails without Authorization header."""
        from fastapi import HTTPException

        from app.routes.livelink import validate_livelink_token

        mock_db = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await validate_livelink_token(mock_db, None, "device_123")

        assert exc_info.value.status_code == 401
        assert "Missing Authorization header" in exc_info.value.detail

    async def test_validate_token_invalid_format(self):
        """Test validation fails with invalid header format."""
        from fastapi import HTTPException

        from app.routes.livelink import validate_livelink_token

        mock_db = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await validate_livelink_token(mock_db, "InvalidFormat", "device_123")

        assert exc_info.value.status_code == 401
        assert "Invalid Authorization header format" in exc_info.value.detail

    async def test_validate_token_invalid_token(self):
        """Test validation fails with invalid token."""
        from fastapi import HTTPException

        from app.routes.livelink import validate_livelink_token

        mock_db = MagicMock()

        with patch("app.routes.livelink.LiveLinkService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.validate_device_token = AsyncMock(return_value=False)
            mock_service.validate_global_token = AsyncMock(return_value=False)
            mock_service_class.return_value = mock_service

            with pytest.raises(HTTPException) as exc_info:
                await validate_livelink_token(mock_db, "Bearer invalid_token", "device_123")

        assert exc_info.value.status_code == 401
        assert "Invalid or expired token" in exc_info.value.detail

    async def test_validate_token_valid_device_token(self):
        """Test validation passes with valid device token."""
        from app.routes.livelink import validate_livelink_token

        mock_db = MagicMock()

        with patch("app.routes.livelink.LiveLinkService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.validate_device_token = AsyncMock(return_value=True)
            mock_service_class.return_value = mock_service

            result = await validate_livelink_token(
                mock_db, "Bearer valid_device_token", "device_123"
            )

        assert result is True

    async def test_validate_token_valid_global_token(self):
        """Test validation passes with valid global token (when device token invalid)."""
        from app.routes.livelink import validate_livelink_token

        mock_db = MagicMock()

        with patch("app.routes.livelink.LiveLinkService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.validate_device_token = AsyncMock(return_value=False)
            mock_service.validate_global_token = AsyncMock(return_value=True)
            mock_service_class.return_value = mock_service

            result = await validate_livelink_token(
                mock_db, "Bearer valid_global_token", "device_123"
            )

        assert result is True

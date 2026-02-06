"""Unit tests for LiveLink token validation.

Tests Bearer token extraction and validation logic in the ingest route.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.routes.livelink import validate_livelink_token


@pytest.mark.unit
@pytest.mark.livelink
class TestValidateLivelinkToken:
    """Test the validate_livelink_token function."""

    @pytest.mark.asyncio
    async def test_rejects_missing_authorization(self):
        """Test that missing Authorization header raises 401."""
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await validate_livelink_token(db, None, "device-1")

        assert exc_info.value.status_code == 401
        assert "Missing Authorization header" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_rejects_non_bearer_format(self):
        """Test that non-Bearer auth format raises 401."""
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await validate_livelink_token(db, "Basic abc123", "device-1")

        assert exc_info.value.status_code == 401
        assert "Invalid Authorization header format" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_rejects_bearer_without_token(self):
        """Test that 'Bearer' without a token value raises 401."""
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await validate_livelink_token(db, "Bearer", "device-1")

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_rejects_bearer_with_extra_parts(self):
        """Test that Bearer with extra parts raises 401."""
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await validate_livelink_token(db, "Bearer token extra", "device-1")

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_accepts_valid_device_token(self):
        """Test that a valid per-device token passes validation."""
        db = AsyncMock()

        with patch("app.routes.livelink.LiveLinkService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.validate_device_token = AsyncMock(return_value=True)
            mock_service.validate_global_token = AsyncMock(return_value=False)

            result = await validate_livelink_token(db, "Bearer valid-device-token", "device-1")

        assert result is True
        mock_service.validate_device_token.assert_awaited_once_with(
            "device-1", "valid-device-token"
        )

    @pytest.mark.asyncio
    async def test_falls_back_to_global_token(self):
        """Test that validation falls back to global token when device token fails."""
        db = AsyncMock()

        with patch("app.routes.livelink.LiveLinkService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.validate_device_token = AsyncMock(return_value=False)
            mock_service.validate_global_token = AsyncMock(return_value=True)

            result = await validate_livelink_token(db, "Bearer global-token", "device-1")

        assert result is True
        mock_service.validate_device_token.assert_awaited_once()
        mock_service.validate_global_token.assert_awaited_once_with("global-token")

    @pytest.mark.asyncio
    async def test_global_token_without_device_id(self):
        """Test global token validation when no device_id provided."""
        db = AsyncMock()

        with patch("app.routes.livelink.LiveLinkService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.validate_global_token = AsyncMock(return_value=True)

            result = await validate_livelink_token(db, "Bearer global-only-token", None)

        assert result is True
        mock_service.validate_global_token.assert_awaited_once_with("global-only-token")

    @pytest.mark.asyncio
    async def test_rejects_invalid_token(self):
        """Test that an invalid token (neither device nor global) raises 401."""
        db = AsyncMock()

        with patch("app.routes.livelink.LiveLinkService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.validate_device_token = AsyncMock(return_value=False)
            mock_service.validate_global_token = AsyncMock(return_value=False)

            with pytest.raises(HTTPException) as exc_info:
                await validate_livelink_token(db, "Bearer bad-token", "device-1")

        assert exc_info.value.status_code == 401
        assert "Invalid or expired token" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_bearer_case_insensitive(self):
        """Test that 'bearer' prefix is case-insensitive."""
        db = AsyncMock()

        with patch("app.routes.livelink.LiveLinkService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.validate_global_token = AsyncMock(return_value=True)

            result = await validate_livelink_token(db, "bearer my-token", None)

        assert result is True

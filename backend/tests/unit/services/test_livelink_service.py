"""Unit tests for LiveLink service.

Tests token management, device operations, and settings helpers.
"""

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.livelink_service import (
    TOKEN_PREFIX,
    LiveLinkService,
)


class TestTokenGeneration:
    """Test token generation and hashing static methods."""

    def test_generate_token_prefix(self):
        """Test that generated tokens have correct prefix."""
        token = LiveLinkService.generate_token()
        assert token.startswith(TOKEN_PREFIX)
        assert token.startswith("ll_")

    def test_generate_token_length(self):
        """Test that generated tokens have sufficient length."""
        token = LiveLinkService.generate_token()
        # Prefix is 3 chars, token_urlsafe produces ~43 chars for 32 bytes
        assert len(token) > 40

    def test_generate_token_uniqueness(self):
        """Test that generated tokens are unique."""
        tokens = {LiveLinkService.generate_token() for _ in range(100)}
        assert len(tokens) == 100  # All unique

    def test_hash_token_deterministic(self):
        """Test that same token produces same hash."""
        token = "ll_test_token_12345"
        hash1 = LiveLinkService.hash_token(token)
        hash2 = LiveLinkService.hash_token(token)
        assert hash1 == hash2

    def test_hash_token_is_sha256(self):
        """Test that token hashing uses SHA-256."""
        token = "ll_test_token_12345"
        expected = hashlib.sha256(token.encode()).hexdigest()
        assert LiveLinkService.hash_token(token) == expected

    def test_hash_token_length(self):
        """Test that hash is correct length (64 hex chars for SHA-256)."""
        token = "ll_test_token_12345"
        token_hash = LiveLinkService.hash_token(token)
        assert len(token_hash) == 64

    def test_hash_token_different_tokens_different_hashes(self):
        """Test that different tokens produce different hashes."""
        hash1 = LiveLinkService.hash_token("ll_token1")
        hash2 = LiveLinkService.hash_token("ll_token2")
        assert hash1 != hash2


class TestTokenMasking:
    """Test token masking for display."""

    def test_mask_token_normal(self):
        """Test masking a normal-length token."""
        token = "ll_abc123xyz789qwerty"
        masked = LiveLinkService.mask_token(token)
        assert masked == "ll_abc***erty"

    def test_mask_token_shows_first_six(self):
        """Test that first 6 characters are shown."""
        token = "ll_abc123xyz789qwerty"
        masked = LiveLinkService.mask_token(token)
        assert masked.startswith("ll_abc")

    def test_mask_token_shows_last_four(self):
        """Test that last 4 characters are shown."""
        token = "ll_abc123xyz789qwerty"
        masked = LiveLinkService.mask_token(token)
        assert masked.endswith("erty")

    def test_mask_token_short_token(self):
        """Test masking a short token (less than 12 chars)."""
        token = "ll_short"
        masked = LiveLinkService.mask_token(token)
        assert masked == "***"

    def test_mask_token_exactly_12_chars(self):
        """Test masking a token with exactly 12 characters."""
        token = "ll_12345678"  # 11 chars
        masked = LiveLinkService.mask_token(token)
        assert masked == "***"

    def test_mask_token_12_chars_boundary(self):
        """Test masking a 12-character token (first valid length)."""
        token = "ll_123456789"  # 12 chars exactly
        masked = LiveLinkService.mask_token(token)
        # 12 chars is >= 12, so it gets masked
        assert masked == "ll_123***6789"

    def test_mask_token_14_chars(self):
        """Test masking a 14-character token."""
        token = "ll_1234567890"  # 13 chars total
        masked = LiveLinkService.mask_token(token)
        assert masked == "ll_123***7890"


@pytest.mark.asyncio
class TestGlobalTokenOperations:
    """Test global token operations with mocked database."""

    async def test_generate_global_token(self):
        """Test generating a new global token."""
        mock_db = AsyncMock()

        with patch("app.services.livelink_service.SettingsService") as mock_settings:
            mock_settings.set = AsyncMock()

            service = LiveLinkService(mock_db)
            token = await service.generate_global_token()

            assert token.startswith(TOKEN_PREFIX)
            mock_settings.set.assert_called_once()
            mock_db.commit.assert_called_once()

    async def test_validate_global_token_valid(self):
        """Test validating a correct global token."""
        mock_db = AsyncMock()
        test_token = "ll_test_token_123"
        token_hash = hashlib.sha256(test_token.encode()).hexdigest()

        with patch("app.services.livelink_service.SettingsService") as mock_settings:
            mock_setting = MagicMock()
            mock_setting.value = token_hash
            mock_settings.get = AsyncMock(return_value=mock_setting)

            service = LiveLinkService(mock_db)
            result = await service.validate_global_token(test_token)

            assert result is True

    async def test_validate_global_token_invalid(self):
        """Test validating an incorrect global token."""
        mock_db = AsyncMock()
        stored_hash = hashlib.sha256(b"correct_token").hexdigest()

        with patch("app.services.livelink_service.SettingsService") as mock_settings:
            mock_setting = MagicMock()
            mock_setting.value = stored_hash
            mock_settings.get = AsyncMock(return_value=mock_setting)

            service = LiveLinkService(mock_db)
            result = await service.validate_global_token("wrong_token")

            assert result is False

    async def test_validate_global_token_no_stored_token(self):
        """Test validation when no global token is stored."""
        mock_db = AsyncMock()

        with patch("app.services.livelink_service.SettingsService") as mock_settings:
            mock_settings.get = AsyncMock(return_value=None)

            service = LiveLinkService(mock_db)
            result = await service.validate_global_token("any_token")

            assert result is False

    async def test_validate_global_token_empty_value(self):
        """Test validation when stored token value is empty."""
        mock_db = AsyncMock()

        with patch("app.services.livelink_service.SettingsService") as mock_settings:
            mock_setting = MagicMock()
            mock_setting.value = None
            mock_settings.get = AsyncMock(return_value=mock_setting)

            service = LiveLinkService(mock_db)
            result = await service.validate_global_token("any_token")

            assert result is False


@pytest.mark.asyncio
class TestDeviceTokenOperations:
    """Test device-specific token operations."""

    async def test_generate_device_token_success(self):
        """Test generating a device token for existing device."""
        mock_db = AsyncMock()
        mock_device = MagicMock()
        mock_device.device_token_hash = None

        with patch.object(LiveLinkService, "get_device_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_device

            service = LiveLinkService(mock_db)
            token = await service.generate_device_token("device_123")

            assert token is not None
            assert token.startswith(TOKEN_PREFIX)
            assert mock_device.device_token_hash is not None
            mock_db.commit.assert_called_once()

    async def test_generate_device_token_device_not_found(self):
        """Test generating a device token when device doesn't exist."""
        mock_db = AsyncMock()

        with patch.object(LiveLinkService, "get_device_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            service = LiveLinkService(mock_db)
            token = await service.generate_device_token("nonexistent")

            assert token is None
            mock_db.commit.assert_not_called()

    async def test_revoke_device_token_success(self):
        """Test revoking a device token."""
        mock_db = AsyncMock()
        mock_device = MagicMock()
        mock_device.device_token_hash = "some_hash"

        with patch.object(LiveLinkService, "get_device_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_device

            service = LiveLinkService(mock_db)
            result = await service.revoke_device_token("device_123")

            assert result is True
            assert mock_device.device_token_hash is None
            mock_db.commit.assert_called_once()

    async def test_revoke_device_token_device_not_found(self):
        """Test revoking token for nonexistent device."""
        mock_db = AsyncMock()

        with patch.object(LiveLinkService, "get_device_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            service = LiveLinkService(mock_db)
            result = await service.revoke_device_token("nonexistent")

            assert result is False
            mock_db.commit.assert_not_called()

    async def test_validate_device_token_valid(self):
        """Test validating a correct device token."""
        mock_db = AsyncMock()
        test_token = "ll_device_token_123"
        token_hash = hashlib.sha256(test_token.encode()).hexdigest()

        mock_device = MagicMock()
        mock_device.device_token_hash = token_hash

        with patch.object(LiveLinkService, "get_device_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_device

            service = LiveLinkService(mock_db)
            result = await service.validate_device_token("device_123", test_token)

            assert result is True

    async def test_validate_device_token_invalid(self):
        """Test validating an incorrect device token."""
        mock_db = AsyncMock()
        token_hash = hashlib.sha256(b"correct_token").hexdigest()

        mock_device = MagicMock()
        mock_device.device_token_hash = token_hash

        with patch.object(LiveLinkService, "get_device_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_device

            service = LiveLinkService(mock_db)
            result = await service.validate_device_token("device_123", "wrong_token")

            assert result is False

    async def test_validate_device_token_no_hash(self):
        """Test validation when device has no token hash."""
        mock_db = AsyncMock()

        mock_device = MagicMock()
        mock_device.device_token_hash = None

        with patch.object(LiveLinkService, "get_device_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_device

            service = LiveLinkService(mock_db)
            result = await service.validate_device_token("device_123", "any_token")

            assert result is False


@pytest.mark.asyncio
class TestTokenValidationFlow:
    """Test combined token validation flow."""

    async def test_validate_token_device_token_first(self):
        """Test that device token is checked before global token."""
        mock_db = AsyncMock()

        service = LiveLinkService(mock_db)

        with (
            patch.object(service, "validate_device_token", new_callable=AsyncMock) as mock_device,
            patch.object(service, "validate_global_token", new_callable=AsyncMock) as mock_global,
        ):
            mock_device.return_value = True

            result = await service.validate_token("test_token", "device_123")

            assert result is True
            mock_device.assert_called_once_with("device_123", "test_token")
            mock_global.assert_not_called()

    async def test_validate_token_fallback_to_global(self):
        """Test that global token is checked when device token fails."""
        mock_db = AsyncMock()

        service = LiveLinkService(mock_db)

        with (
            patch.object(service, "validate_device_token", new_callable=AsyncMock) as mock_device,
            patch.object(service, "validate_global_token", new_callable=AsyncMock) as mock_global,
        ):
            mock_device.return_value = False
            mock_global.return_value = True

            result = await service.validate_token("test_token", "device_123")

            assert result is True
            mock_device.assert_called_once()
            mock_global.assert_called_once_with("test_token")

    async def test_validate_token_no_device_id(self):
        """Test validation with no device_id (global only)."""
        mock_db = AsyncMock()

        service = LiveLinkService(mock_db)

        with (
            patch.object(service, "validate_device_token", new_callable=AsyncMock) as mock_device,
            patch.object(service, "validate_global_token", new_callable=AsyncMock) as mock_global,
        ):
            mock_global.return_value = True

            result = await service.validate_token("test_token", device_id=None)

            assert result is True
            mock_device.assert_not_called()
            mock_global.assert_called_once_with("test_token")


@pytest.mark.asyncio
class TestDeviceManagement:
    """Test device management operations."""

    async def test_link_device_to_vehicle_success(self):
        """Test linking a device to a vehicle."""
        mock_db = AsyncMock()
        mock_device = MagicMock()
        mock_device.vin = None

        with patch.object(LiveLinkService, "get_device_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_device

            service = LiveLinkService(mock_db)
            result = await service.link_device_to_vehicle("device_123", "1HGCM82633A123456")

            assert result is True
            assert mock_device.vin == "1HGCM82633A123456"
            mock_db.commit.assert_called_once()

    async def test_link_device_to_vehicle_not_found(self):
        """Test linking nonexistent device."""
        mock_db = AsyncMock()

        with patch.object(LiveLinkService, "get_device_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            service = LiveLinkService(mock_db)
            result = await service.link_device_to_vehicle("nonexistent", "VIN123")

            assert result is False
            mock_db.commit.assert_not_called()

    async def test_unlink_device_success(self):
        """Test unlinking a device from vehicle."""
        mock_db = AsyncMock()
        mock_device = MagicMock()
        mock_device.vin = "1HGCM82633A123456"
        mock_device.current_session_id = 123

        with patch.object(LiveLinkService, "get_device_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_device

            service = LiveLinkService(mock_db)
            result = await service.unlink_device("device_123")

            assert result is True
            assert mock_device.vin is None
            assert mock_device.current_session_id is None
            mock_db.commit.assert_called_once()

    async def test_unlink_device_not_found(self):
        """Test unlinking nonexistent device."""
        mock_db = AsyncMock()

        with patch.object(LiveLinkService, "get_device_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            service = LiveLinkService(mock_db)
            result = await service.unlink_device("nonexistent")

            assert result is False

    async def test_update_device_all_fields(self):
        """Test updating all device fields."""
        mock_db = AsyncMock()
        mock_device = MagicMock()
        mock_device.label = None
        mock_device.vin = None
        mock_device.enabled = True

        with patch.object(LiveLinkService, "get_device_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_device

            service = LiveLinkService(mock_db)
            result = await service.update_device(
                "device_123", label="My WiCAN", vin="VIN123", enabled=False
            )

            assert result == mock_device
            assert mock_device.label == "My WiCAN"
            assert mock_device.vin == "VIN123"
            assert mock_device.enabled is False
            mock_db.commit.assert_called_once()

    async def test_update_device_partial(self):
        """Test updating only some device fields."""
        mock_db = AsyncMock()
        mock_device = MagicMock()
        mock_device.label = "Old Label"
        mock_device.vin = "OLD_VIN"
        mock_device.enabled = True

        with patch.object(LiveLinkService, "get_device_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_device

            service = LiveLinkService(mock_db)
            result = await service.update_device("device_123", label="New Label")

            assert result == mock_device
            assert mock_device.label == "New Label"
            # Other fields unchanged by the update call (not reset)
            mock_db.commit.assert_called_once()

    async def test_update_device_not_found(self):
        """Test updating nonexistent device."""
        mock_db = AsyncMock()

        with patch.object(LiveLinkService, "get_device_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            service = LiveLinkService(mock_db)
            result = await service.update_device("nonexistent", label="Test")

            assert result is None

    async def test_delete_device_success(self):
        """Test deleting a device."""
        mock_db = AsyncMock()
        mock_device = MagicMock()

        with patch.object(LiveLinkService, "get_device_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_device

            service = LiveLinkService(mock_db)
            result = await service.delete_device("device_123")

            assert result is True
            mock_db.delete.assert_called_once_with(mock_device)
            mock_db.commit.assert_called_once()

    async def test_delete_device_not_found(self):
        """Test deleting nonexistent device."""
        mock_db = AsyncMock()

        with patch.object(LiveLinkService, "get_device_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            service = LiveLinkService(mock_db)
            result = await service.delete_device("nonexistent")

            assert result is False
            mock_db.delete.assert_not_called()


@pytest.mark.asyncio
class TestSettingsHelpers:
    """Test settings helper methods."""

    async def test_is_enabled_true(self):
        """Test is_enabled returns True when enabled."""
        mock_db = AsyncMock()

        with patch("app.services.livelink_service.SettingsService") as mock_settings:
            mock_setting = MagicMock()
            mock_setting.value = "true"
            mock_settings.get = AsyncMock(return_value=mock_setting)

            service = LiveLinkService(mock_db)
            result = await service.is_enabled()

            assert result is True

    async def test_is_enabled_false(self):
        """Test is_enabled returns False when disabled."""
        mock_db = AsyncMock()

        with patch("app.services.livelink_service.SettingsService") as mock_settings:
            mock_setting = MagicMock()
            mock_setting.value = "false"
            mock_settings.get = AsyncMock(return_value=mock_setting)

            service = LiveLinkService(mock_db)
            result = await service.is_enabled()

            assert result is False

    async def test_is_enabled_no_setting(self):
        """Test is_enabled returns False when setting doesn't exist."""
        mock_db = AsyncMock()

        with patch("app.services.livelink_service.SettingsService") as mock_settings:
            mock_settings.get = AsyncMock(return_value=None)

            service = LiveLinkService(mock_db)
            result = await service.is_enabled()

            assert result is False

    async def test_get_session_timeout_with_value(self):
        """Test getting session timeout when configured."""
        mock_db = AsyncMock()

        with patch("app.services.livelink_service.SettingsService") as mock_settings:
            mock_setting = MagicMock()
            mock_setting.value = "10"
            mock_settings.get = AsyncMock(return_value=mock_setting)

            service = LiveLinkService(mock_db)
            result = await service.get_session_timeout_minutes()

            assert result == 10

    async def test_get_session_timeout_default(self):
        """Test getting session timeout default when not configured."""
        mock_db = AsyncMock()

        with patch("app.services.livelink_service.SettingsService") as mock_settings:
            mock_settings.get = AsyncMock(return_value=None)

            service = LiveLinkService(mock_db)
            result = await service.get_session_timeout_minutes()

            assert result == 5  # Default value

    async def test_get_device_offline_timeout_with_value(self):
        """Test getting device offline timeout when configured."""
        mock_db = AsyncMock()

        with patch("app.services.livelink_service.SettingsService") as mock_settings:
            mock_setting = MagicMock()
            mock_setting.value = "30"
            mock_settings.get = AsyncMock(return_value=mock_setting)

            service = LiveLinkService(mock_db)
            result = await service.get_device_offline_timeout_minutes()

            assert result == 30

    async def test_get_device_offline_timeout_default(self):
        """Test getting device offline timeout default."""
        mock_db = AsyncMock()

        with patch("app.services.livelink_service.SettingsService") as mock_settings:
            mock_settings.get = AsyncMock(return_value=None)

            service = LiveLinkService(mock_db)
            result = await service.get_device_offline_timeout_minutes()

            assert result == 15  # Default value

    async def test_get_retention_days_with_value(self):
        """Test getting retention days when configured."""
        mock_db = AsyncMock()

        with patch("app.services.livelink_service.SettingsService") as mock_settings:
            mock_setting = MagicMock()
            mock_setting.value = "365"
            mock_settings.get = AsyncMock(return_value=mock_setting)

            service = LiveLinkService(mock_db)
            result = await service.get_retention_days()

            assert result == 365

    async def test_get_retention_days_default(self):
        """Test getting retention days default."""
        mock_db = AsyncMock()

        with patch("app.services.livelink_service.SettingsService") as mock_settings:
            mock_settings.get = AsyncMock(return_value=None)

            service = LiveLinkService(mock_db)
            result = await service.get_retention_days()

            assert result == 90  # Default value

    async def test_get_alert_cooldown_with_value(self):
        """Test getting alert cooldown when configured."""
        mock_db = AsyncMock()

        with patch("app.services.livelink_service.SettingsService") as mock_settings:
            mock_setting = MagicMock()
            mock_setting.value = "60"
            mock_settings.get = AsyncMock(return_value=mock_setting)

            service = LiveLinkService(mock_db)
            result = await service.get_alert_cooldown_minutes()

            assert result == 60

    async def test_get_alert_cooldown_default(self):
        """Test getting alert cooldown default."""
        mock_db = AsyncMock()

        with patch("app.services.livelink_service.SettingsService") as mock_settings:
            mock_settings.get = AsyncMock(return_value=None)

            service = LiveLinkService(mock_db)
            result = await service.get_alert_cooldown_minutes()

            assert result == 30  # Default value

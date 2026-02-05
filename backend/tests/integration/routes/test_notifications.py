"""
Integration tests for notification routes.

Tests notification provider connection tests (admin-only endpoints).
Uses mocking to avoid actual external API calls.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.models.settings import Setting


async def set_settings(db_session, settings_dict: dict[str, str]) -> None:
    """Helper to set settings, updating existing or creating new."""
    for key, value in settings_dict.items():
        result = await db_session.execute(select(Setting).where(Setting.key == key))
        existing = result.scalar_one_or_none()
        if existing:
            existing.value = value
        else:
            db_session.add(Setting(key=key, value=value))
    await db_session.commit()


async def clear_notification_settings(db_session) -> None:
    """Clear all notification-related settings."""
    notification_keys = [
        "ntfy_enabled",
        "ntfy_server",
        "ntfy_topic",
        "ntfy_token",
        "gotify_enabled",
        "gotify_server",
        "gotify_token",
        "pushover_enabled",
        "pushover_user_key",
        "pushover_api_token",
        "slack_enabled",
        "slack_webhook_url",
        "discord_enabled",
        "discord_webhook_url",
        "telegram_enabled",
        "telegram_bot_token",
        "telegram_chat_id",
        "email_enabled",
        "email_smtp_host",
        "email_smtp_port",
        "email_smtp_user",
        "email_smtp_password",
        "email_from",
        "email_to",
    ]
    await db_session.execute(delete(Setting).where(Setting.key.in_(notification_keys)))
    await db_session.commit()


@pytest.fixture(autouse=True)
async def clean_notification_settings(db_session):
    """Clean notification settings before each test."""
    await clear_notification_settings(db_session)
    yield
    await clear_notification_settings(db_session)


@pytest.mark.integration
@pytest.mark.asyncio
class TestNotificationRoutes:
    """Test notification API endpoints."""

    # -------------------------------------------------------------------------
    # ntfy tests
    # -------------------------------------------------------------------------

    async def test_ntfy_disabled(self, client: AsyncClient, auth_headers):
        """Test ntfy test when notifications are disabled."""
        response = await client.post(
            "/api/notifications/test/ntfy",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "disabled" in data["message"].lower()

    async def test_ntfy_not_configured(self, client: AsyncClient, auth_headers, db_session):
        """Test ntfy test when enabled but not configured."""
        await set_settings(db_session, {"ntfy_enabled": "true"})

        response = await client.post(
            "/api/notifications/test/ntfy",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "not configured" in data["message"].lower()

    async def test_ntfy_success(self, client: AsyncClient, auth_headers, db_session):
        """Test ntfy test success with mocked HTTP."""
        await set_settings(
            db_session,
            {
                "ntfy_enabled": "true",
                "ntfy_server": "https://ntfy.example.com",
                "ntfy_topic": "test-topic",
            },
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            response = await client.post(
                "/api/notifications/test/ntfy",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "sent" in data["message"].lower()

    # -------------------------------------------------------------------------
    # gotify tests
    # -------------------------------------------------------------------------

    async def test_gotify_disabled(self, client: AsyncClient, auth_headers):
        """Test gotify test when notifications are disabled."""
        response = await client.post(
            "/api/notifications/test/gotify",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "disabled" in data["message"].lower()

    async def test_gotify_success(self, client: AsyncClient, auth_headers, db_session):
        """Test gotify test success with mocked HTTP."""
        await set_settings(
            db_session,
            {
                "gotify_enabled": "true",
                "gotify_server": "https://gotify.example.com",
                "gotify_token": "test-token",
            },
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            response = await client.post(
                "/api/notifications/test/gotify",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    # -------------------------------------------------------------------------
    # pushover tests
    # -------------------------------------------------------------------------

    async def test_pushover_disabled(self, client: AsyncClient, auth_headers):
        """Test pushover test when notifications are disabled."""
        response = await client.post(
            "/api/notifications/test/pushover",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "disabled" in data["message"].lower()

    async def test_pushover_success(self, client: AsyncClient, auth_headers, db_session):
        """Test pushover test success with mocked HTTP."""
        await set_settings(
            db_session,
            {
                "pushover_enabled": "true",
                "pushover_user_key": "test-user-key",
                "pushover_api_token": "test-api-token",
            },
        )

        # Pushover makes two calls: validate + message
        mock_validate_response = MagicMock()
        mock_validate_response.status_code = 200
        mock_validate_response.json = MagicMock(return_value={"status": 1})

        mock_message_response = MagicMock()
        mock_message_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(
                side_effect=[mock_validate_response, mock_message_response]
            )
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            response = await client.post(
                "/api/notifications/test/pushover",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    # -------------------------------------------------------------------------
    # slack tests
    # -------------------------------------------------------------------------

    async def test_slack_disabled(self, client: AsyncClient, auth_headers):
        """Test slack test when notifications are disabled."""
        response = await client.post(
            "/api/notifications/test/slack",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "disabled" in data["message"].lower()

    async def test_slack_success(self, client: AsyncClient, auth_headers, db_session):
        """Test slack test success with mocked HTTP."""
        await set_settings(
            db_session,
            {
                "slack_enabled": "true",
                "slack_webhook_url": "https://hooks.slack.com/test",
            },
        )

        mock_response = MagicMock()
        mock_response.text = "ok"

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            response = await client.post(
                "/api/notifications/test/slack",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    # -------------------------------------------------------------------------
    # discord tests
    # -------------------------------------------------------------------------

    async def test_discord_disabled(self, client: AsyncClient, auth_headers):
        """Test discord test when notifications are disabled."""
        response = await client.post(
            "/api/notifications/test/discord",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "disabled" in data["message"].lower()

    async def test_discord_success(self, client: AsyncClient, auth_headers, db_session):
        """Test discord test success with mocked HTTP."""
        await set_settings(
            db_session,
            {
                "discord_enabled": "true",
                "discord_webhook_url": "https://discord.com/api/webhooks/test",
            },
        )

        mock_response = MagicMock()
        mock_response.status_code = 204

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            response = await client.post(
                "/api/notifications/test/discord",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    # -------------------------------------------------------------------------
    # telegram tests
    # -------------------------------------------------------------------------

    async def test_telegram_disabled(self, client: AsyncClient, auth_headers):
        """Test telegram test when notifications are disabled."""
        response = await client.post(
            "/api/notifications/test/telegram",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "disabled" in data["message"].lower()

    async def test_telegram_success(self, client: AsyncClient, auth_headers, db_session):
        """Test telegram test success with mocked HTTP."""
        await set_settings(
            db_session,
            {
                "telegram_enabled": "true",
                "telegram_bot_token": "test-bot-token",
                "telegram_chat_id": "123456789",
            },
        )

        # Telegram makes two calls: getMe + sendMessage
        mock_getme_response = MagicMock()
        mock_getme_response.status_code = 200

        mock_send_response = MagicMock()
        mock_send_response.json = MagicMock(return_value={"ok": True})

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_getme_response)
            mock_instance.post = AsyncMock(return_value=mock_send_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            response = await client.post(
                "/api/notifications/test/telegram",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    # -------------------------------------------------------------------------
    # email tests
    # -------------------------------------------------------------------------

    async def test_email_disabled(self, client: AsyncClient, auth_headers):
        """Test email test when notifications are disabled."""
        response = await client.post(
            "/api/notifications/test/email",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "disabled" in data["message"].lower()

    async def test_email_not_configured(self, client: AsyncClient, auth_headers, db_session):
        """Test email test when enabled but not fully configured."""
        await set_settings(db_session, {"email_enabled": "true"})

        response = await client.post(
            "/api/notifications/test/email",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "incomplete" in data["message"].lower()

    async def test_email_success(self, client: AsyncClient, auth_headers, db_session):
        """Test email test success with mocked SMTP."""
        await set_settings(
            db_session,
            {
                "email_enabled": "true",
                "email_smtp_host": "smtp.example.com",
                "email_smtp_port": "587",
                "email_smtp_user": "test@example.com",
                "email_smtp_password": "test-password",
                "email_from": "test@example.com",
                "email_to": "recipient@example.com",
            },
        )

        with patch("aiosmtplib.send") as mock_send:
            mock_send.return_value = None

            response = await client.post(
                "/api/notifications/test/email",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "sent" in data["message"].lower()

    # -------------------------------------------------------------------------
    # Authorization tests
    # -------------------------------------------------------------------------

    async def test_unauthorized(self, client: AsyncClient):
        """Test that unauthenticated users cannot access notification tests."""
        response = await client.post("/api/notifications/test/ntfy")
        assert response.status_code == 401

    async def test_non_admin_forbidden(self, client: AsyncClient, db_session):
        """Test that non-admin users cannot access notification tests."""
        from sqlalchemy import or_

        from app.models.user import User
        from app.services.auth import create_access_token

        # Check if non-admin user already exists
        result = await db_session.execute(
            select(User).where(
                or_(User.username == "regularuser", User.email == "regular@example.com")
            )
        )
        non_admin = result.scalar_one_or_none()

        if not non_admin:
            non_admin = User(
                username="regularuser",
                email="regular@example.com",
                hashed_password="$argon2id$v=19$m=102400,t=2,p=8$NNbLa8SMLODWY2Es68EvLw$hiGLA+DtO213EMAMi8D8gXvvyjP8EVMFIHWp7SlUVnI",
                is_active=True,
                is_admin=False,
            )
            db_session.add(non_admin)
            await db_session.commit()
            await db_session.refresh(non_admin)

        # Create token for non-admin user
        token = create_access_token(data={"sub": str(non_admin.id), "username": non_admin.username})
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.post(
            "/api/notifications/test/ntfy",
            headers=headers,
        )

        assert response.status_code == 403

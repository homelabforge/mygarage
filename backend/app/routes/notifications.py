"""Notification API endpoints for testing notification services."""

import logging
from typing import Dict

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.services.auth import get_current_admin_user
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])


async def _get_setting(db: AsyncSession, key: str, default: str = "") -> str:
    """Get a setting value."""
    setting = await SettingsService.get(db, key)
    return setting.value if setting and setting.value else default


async def _get_setting_bool(db: AsyncSession, key: str, default: bool = False) -> bool:
    """Get a boolean setting value."""
    value = await _get_setting(db, key, str(default).lower())
    return value.lower() in ("true", "1", "yes")


@router.post("/test/ntfy")
async def test_ntfy_connection(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> Dict:
    """Test ntfy server connection."""
    try:
        ntfy_enabled = await _get_setting_bool(db, "ntfy_enabled")
        ntfy_server = await _get_setting(db, "ntfy_server")
        ntfy_topic = await _get_setting(db, "ntfy_topic")
        ntfy_token = await _get_setting(db, "ntfy_token")

        if not ntfy_enabled:
            return {"success": False, "message": "ntfy notifications are disabled"}

        if not ntfy_server or not ntfy_topic:
            return {"success": False, "message": "ntfy server or topic not configured"}

        server_url = ntfy_server.rstrip("/")
        headers: dict[str, str] = {}
        if ntfy_token:
            headers["Authorization"] = f"Bearer {ntfy_token}"
        headers["Title"] = "MyGarage Test Notification"
        headers["Priority"] = "low"
        headers["Tags"] = "white_check_mark,car"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{server_url}/{ntfy_topic}",
                content="This is a test notification from MyGarage.",
                headers=headers,
            )
            response.raise_for_status()
            return {"success": True, "message": "Test notification sent"}
    except Exception as e:
        logger.error("ntfy test failed: %s", e)
        return {"success": False, "message": str(e)}


@router.post("/test/gotify")
async def test_gotify_connection(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> Dict:
    """Test Gotify server connection."""
    try:
        gotify_enabled = await _get_setting_bool(db, "gotify_enabled")
        gotify_server = await _get_setting(db, "gotify_server")
        gotify_token = await _get_setting(db, "gotify_token")

        if not gotify_enabled:
            return {"success": False, "message": "Gotify notifications are disabled"}

        if not gotify_server or not gotify_token:
            return {
                "success": False,
                "message": "Gotify server or token not configured",
            }

        server_url = gotify_server.rstrip("/")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{server_url}/message",
                headers={"X-Gotify-Key": gotify_token},
                json={
                    "title": "MyGarage Test Notification",
                    "message": "This is a test notification from MyGarage.",
                    "priority": 5,
                },
            )
            response.raise_for_status()
            return {"success": True, "message": "Test notification sent"}
    except Exception as e:
        logger.error("Gotify test failed: %s", e)
        return {"success": False, "message": str(e)}


@router.post("/test/pushover")
async def test_pushover_connection(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> Dict:
    """Test Pushover connection."""
    try:
        pushover_enabled = await _get_setting_bool(db, "pushover_enabled")
        user_key = await _get_setting(db, "pushover_user_key")
        api_token = await _get_setting(db, "pushover_api_token")

        if not pushover_enabled:
            return {"success": False, "message": "Pushover notifications are disabled"}

        if not user_key or not api_token:
            return {"success": False, "message": "Pushover credentials not configured"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Validate credentials first
            validate_response = await client.post(
                "https://api.pushover.net/1/users/validate.json",
                data={"token": api_token, "user": user_key},
            )
            if validate_response.status_code != 200:
                return {"success": False, "message": "Invalid Pushover credentials"}

            result = validate_response.json()
            if result.get("status") != 1:
                return {
                    "success": False,
                    "message": f"Invalid credentials: {result.get('errors', [])}",
                }

            # Send test notification
            response = await client.post(
                "https://api.pushover.net/1/messages.json",
                data={
                    "token": api_token,
                    "user": user_key,
                    "title": "MyGarage Test Notification",
                    "message": "This is a test notification from MyGarage.",
                    "priority": -1,
                },
            )
            response.raise_for_status()
            return {"success": True, "message": "Test notification sent"}
    except Exception as e:
        logger.error("Pushover test failed: %s", e)
        return {"success": False, "message": str(e)}


@router.post("/test/slack")
async def test_slack_connection(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> Dict:
    """Test Slack webhook connection."""
    try:
        slack_enabled = await _get_setting_bool(db, "slack_enabled")
        webhook_url = await _get_setting(db, "slack_webhook_url")

        if not slack_enabled:
            return {"success": False, "message": "Slack notifications are disabled"}

        if not webhook_url:
            return {"success": False, "message": "Slack webhook URL not configured"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                webhook_url,
                json={
                    "attachments": [
                        {
                            "color": "#36a64f",
                            "title": "MyGarage Test Notification",
                            "text": "This is a test notification from MyGarage.",
                            "footer": "MyGarage",
                        }
                    ]
                },
            )
            if response.text == "ok":
                return {"success": True, "message": "Test notification sent"}
            return {
                "success": False,
                "message": f"Unexpected response: {response.text}",
            }
    except Exception as e:
        logger.error("Slack test failed: %s", e)
        return {"success": False, "message": str(e)}


@router.post("/test/discord")
async def test_discord_connection(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> Dict:
    """Test Discord webhook connection."""
    try:
        discord_enabled = await _get_setting_bool(db, "discord_enabled")
        webhook_url = await _get_setting(db, "discord_webhook_url")

        if not discord_enabled:
            return {"success": False, "message": "Discord notifications are disabled"}

        if not webhook_url:
            return {"success": False, "message": "Discord webhook URL not configured"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                webhook_url,
                json={
                    "embeds": [
                        {
                            "title": "MyGarage Test Notification",
                            "description": "This is a test notification from MyGarage.",
                            "color": 3580497,  # Green
                            "footer": {"text": "MyGarage"},
                        }
                    ]
                },
            )
            if response.status_code == 204:
                return {"success": True, "message": "Test notification sent"}
            response.raise_for_status()
            return {"success": False, "message": "Unexpected response"}
    except Exception as e:
        logger.error("Discord test failed: %s", e)
        return {"success": False, "message": str(e)}


@router.post("/test/telegram")
async def test_telegram_connection(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> Dict:
    """Test Telegram bot connection."""
    try:
        telegram_enabled = await _get_setting_bool(db, "telegram_enabled")
        bot_token = await _get_setting(db, "telegram_bot_token")
        chat_id = await _get_setting(db, "telegram_chat_id")

        if not telegram_enabled:
            return {"success": False, "message": "Telegram notifications are disabled"}

        if not bot_token or not chat_id:
            return {
                "success": False,
                "message": "Telegram bot token or chat ID not configured",
            }

        base_url = f"https://api.telegram.org/bot{bot_token}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Verify bot token
            me_response = await client.get(f"{base_url}/getMe")
            if me_response.status_code != 200:
                return {"success": False, "message": "Invalid bot token"}

            # Send test message
            response = await client.post(
                f"{base_url}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": "<b>MyGarage Test Notification</b>\n\nThis is a test notification from MyGarage.",
                    "parse_mode": "HTML",
                },
            )
            result = response.json()
            if result.get("ok"):
                return {"success": True, "message": "Test notification sent"}
            return {
                "success": False,
                "message": result.get("description", "Unknown error"),
            }
    except Exception as e:
        logger.error("Telegram test failed: %s", e)
        return {"success": False, "message": str(e)}


@router.post("/test/email")
async def test_email_connection(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> Dict:
    """Test email SMTP connection."""
    try:
        import aiosmtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        email_enabled = await _get_setting_bool(db, "email_enabled")
        smtp_host = await _get_setting(db, "email_smtp_host")
        smtp_port_str = await _get_setting(db, "email_smtp_port", "587")
        smtp_user = await _get_setting(db, "email_smtp_user")
        smtp_password = await _get_setting(db, "email_smtp_password")
        from_address = await _get_setting(db, "email_from")
        to_address = await _get_setting(db, "email_to")
        use_tls = await _get_setting_bool(db, "email_smtp_tls", default=True)

        if not email_enabled:
            return {"success": False, "message": "Email notifications are disabled"}

        if not all([smtp_host, smtp_user, smtp_password, from_address, to_address]):
            return {"success": False, "message": "Email settings incomplete"}

        try:
            smtp_port = int(smtp_port_str)
        except ValueError:
            smtp_port = 587

        # Create test email
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "MyGarage: Test Notification"
        msg["From"] = from_address
        msg["To"] = to_address

        text_content = (
            "MyGarage Test Notification\n\nThis is a test notification from MyGarage."
        )
        html_content = """
        <html>
        <body style="font-family: Arial, sans-serif;">
            <h2>MyGarage Test Notification</h2>
            <p>This is a test notification from MyGarage.</p>
            <p>If you received this, your email notification settings are working correctly.</p>
        </body>
        </html>
        """

        msg.attach(MIMEText(text_content, "plain"))
        msg.attach(MIMEText(html_content, "html"))

        await aiosmtplib.send(
            msg,
            hostname=smtp_host,
            port=smtp_port,
            username=smtp_user,
            password=smtp_password,
            start_tls=use_tls,
        )

        return {"success": True, "message": "Test email sent"}
    except Exception as e:
        logger.error("Email test failed: %s", e)
        return {"success": False, "message": str(e)}

"""Notification API endpoints for testing notification services and in-app inbox."""

import logging
from datetime import date, timedelta
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.reminder import Reminder
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_share import VehicleShare
from app.services.auth import get_current_admin_user, require_auth
from app.services.hours_service import latest_engine_hours_and_date
from app.services.odometer_service import latest_odometer_km_and_date
from app.services.reminder_service import is_reminder_overdue
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
) -> dict[str, Any]:
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
        return {
            "success": False,
            "message": "Failed to send test notification. Check server logs for details.",
        }


@router.post("/test/gotify")
async def test_gotify_connection(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
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
        return {
            "success": False,
            "message": "Failed to connect to Gotify server. Check server logs for details.",
        }


@router.post("/test/pushover")
async def test_pushover_connection(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
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
        return {
            "success": False,
            "message": "Failed to send Pushover test. Check server logs for details.",
        }


@router.post("/test/slack")
async def test_slack_connection(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
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
        return {
            "success": False,
            "message": "Failed to send Slack test. Check server logs for details.",
        }


@router.post("/test/discord")
async def test_discord_connection(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
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
        return {
            "success": False,
            "message": "Failed to send Discord test. Check server logs for details.",
        }


@router.post("/test/matrix")
async def test_matrix_connection(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """Test Matrix homeserver connection."""
    try:
        from app.services.notifications.matrix import MatrixNotificationService

        matrix_enabled = await _get_setting_bool(db, "matrix_enabled")
        homeserver = await _get_setting(db, "matrix_homeserver")
        access_token = await _get_setting(db, "matrix_access_token")
        room_id = await _get_setting(db, "matrix_room_id")

        if not matrix_enabled:
            return {"success": False, "message": "Matrix notifications are disabled"}

        if not homeserver or not access_token or not room_id:
            return {
                "success": False,
                "message": "Matrix homeserver, access token, or room ID not configured",
            }

        service = MatrixNotificationService(homeserver, access_token, room_id)
        try:
            success, message = await service.test_connection()
            return {"success": success, "message": message}
        finally:
            await service.close()
    except Exception as e:
        logger.error("Matrix test failed: %s", e)
        return {
            "success": False,
            "message": "Failed to send Matrix test. Check server logs for details.",
        }


@router.post("/test/telegram")
async def test_telegram_connection(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
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
        return {
            "success": False,
            "message": "Failed to send Telegram test. Check server logs for details.",
        }


@router.post("/test/email")
async def test_email_connection(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """Test email SMTP connection."""
    try:
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        import aiosmtplib

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

        text_content = "MyGarage Test Notification\n\nThis is a test notification from MyGarage."
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
        return {
            "success": False,
            "message": "Failed to send email test. Check server logs for details.",
        }


class InboxItem(BaseModel):
    """In-app notification derived from overdue / upcoming reminders."""

    id: str
    kind: Literal["reminder_overdue", "reminder_upcoming"]
    title: str
    body: str
    vin: str
    vehicle_nickname: str | None = None
    href: str
    severity: Literal["warning", "critical", "info"] = "info"


class InboxResponse(BaseModel):
    """Notification inbox payload."""

    items: list[InboxItem] = Field(default_factory=list)
    unread_count: int = 0


async def _inbox_vehicles(db: AsyncSession, current_user: User | None) -> list[Vehicle]:
    if current_user is None:
        result = await db.execute(select(Vehicle).where(Vehicle.archived_at.is_(None)))
        return list(result.scalars().all())

    owned_result = await db.execute(
        select(Vehicle).where(
            Vehicle.user_id == current_user.id,
            Vehicle.archived_at.is_(None),
        )
    )
    owned = list(owned_result.scalars().all())
    owned_vins = {v.vin for v in owned}
    shared_query = (
        select(Vehicle)
        .join(VehicleShare, VehicleShare.vehicle_vin == Vehicle.vin)
        .where(
            VehicleShare.user_id == current_user.id,
            Vehicle.archived_at.is_(None),
        )
    )
    if owned_vins:
        shared_query = shared_query.where(Vehicle.vin.not_in(owned_vins))
    shared_result = await db.execute(shared_query)
    return owned + list(shared_result.scalars().all())


@router.get("/inbox", response_model=InboxResponse)
async def notification_inbox(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> InboxResponse:
    """Return actionable in-app alerts (overdue and soon-due reminders)."""
    vehicles = await _inbox_vehicles(db, current_user)
    today = date.today()
    soon = today + timedelta(days=14)
    items: list[InboxItem] = []

    for vehicle in vehicles:
        pending_result = await db.execute(
            select(Reminder).where(Reminder.vin == vehicle.vin, Reminder.status == "pending")
        )
        pending = list(pending_result.scalars().all())
        if not pending:
            continue

        current_km, _ = await latest_odometer_km_and_date(db, vehicle.vin)
        current_hours, _ = await latest_engine_hours_and_date(db, vehicle.vin)

        for reminder in pending:
            overdue = is_reminder_overdue(reminder, current_km, current_hours, today)
            upcoming = False
            if not overdue and reminder.due_date is not None:
                upcoming = today <= reminder.due_date <= soon

            if not overdue and not upcoming:
                continue

            kind: Literal["reminder_overdue", "reminder_upcoming"] = (
                "reminder_overdue" if overdue else "reminder_upcoming"
            )
            severity: Literal["warning", "critical", "info"] = (
                "critical" if overdue else "warning"
            )
            due_bits: list[str] = []
            if reminder.due_date is not None:
                due_bits.append(f"due {reminder.due_date.isoformat()}")
            body = (
                f"{vehicle.nickname or vehicle.vin}"
                + (f" — {', '.join(due_bits)}" if due_bits else "")
            )
            items.append(
                InboxItem(
                    id=f"reminder-{reminder.id}",
                    kind=kind,
                    title=reminder.title,
                    body=body,
                    vin=vehicle.vin,
                    vehicle_nickname=vehicle.nickname,
                    href=f"/vehicles/{vehicle.vin}?tab=reminders",
                    severity=severity,
                )
            )

    # Overdue first, then upcoming; stable by title
    items.sort(key=lambda i: (0 if i.kind == "reminder_overdue" else 1, i.title.lower()))
    return InboxResponse(items=items, unread_count=len(items))

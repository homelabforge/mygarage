"""Email notification service."""

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import aiosmtplib

from app.services.notifications.base import NotificationService

logger = logging.getLogger(__name__)

# Map standard priorities to email subject prefixes
PRIORITY_PREFIX = {
    "min": "",
    "low": "",
    "default": "",
    "high": "[Important] ",
    "urgent": "[URGENT] ",
}


class EmailNotificationService(NotificationService):
    """SMTP email notification service implementation."""

    service_name = "email"

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        smtp_user: str,
        smtp_password: str,
        from_address: str,
        to_address: str,
        use_tls: bool = True,
    ) -> None:
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.from_address = from_address
        self.to_address = to_address
        self.use_tls = use_tls

    async def close(self) -> None:
        """No persistent connection to close."""
        pass

    async def send(
        self,
        title: str,
        message: str,
        priority: str = "default",
        tags: Optional[list[str]] = None,
        url: Optional[str] = None,
    ) -> bool:
        try:
            prefix = PRIORITY_PREFIX.get(priority, "")
            subject = f"{prefix}MyGarage: {title}"

            # Create multipart message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.from_address
            msg["To"] = self.to_address

            # Plain text version
            text_content = f"{title}\n\n{message}"
            if url:
                text_content += f"\n\nView details: {url}"
            text_content += "\n\n--\nSent from MyGarage"

            # HTML version
            html_content = f"""
            <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background-color: #3b82f6; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
                    <h1 style="margin: 0; font-size: 20px;">{title}</h1>
                </div>
                <div style="padding: 20px; background-color: #f8fafc; border: 1px solid #e2e8f0; border-top: none;">
                    <p style="color: #1e293b; line-height: 1.6;">{message}</p>
                    {"<p><a href='" + url + "' style='color: #3b82f6;'>View Details</a></p>" if url else ""}
                </div>
                <div style="padding: 15px; background-color: #e2e8f0; border-radius: 0 0 8px 8px; text-align: center;">
                    <p style="color: #64748b; font-size: 12px; margin: 0;">Sent from MyGarage</p>
                </div>
            </body>
            </html>
            """

            msg.attach(MIMEText(text_content, "plain"))
            msg.attach(MIMEText(html_content, "html"))

            # Send email
            await aiosmtplib.send(
                msg,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.smtp_user,
                password=self.smtp_password,
                start_tls=self.use_tls,
            )

            logger.info("[email] Sent notification: %s", title)
            return True

        except aiosmtplib.SMTPException as e:
            logger.error("[email] SMTP error: %s", e)
            return False
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.error("[email] Connection error: %s", e)
            return False
        except (ValueError, KeyError) as e:
            logger.error("[email] Invalid data: %s", e)
            return False

    async def test_connection(self) -> tuple[bool, str]:
        try:
            success = await self.send(
                title="Test Notification",
                message="This is a test notification from MyGarage. If you received this, your email notification settings are working correctly.",
                priority="low",
            )

            if success:
                return True, "Test email sent successfully"
            return False, "Failed to send test email"

        except Exception as e:
            return False, f"Connection test failed: {str(e)}"

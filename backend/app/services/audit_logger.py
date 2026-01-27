"""Audit logging service for tracking sensitive operations."""

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.user import User

logger = logging.getLogger(__name__)


class AuditLogger:
    """Service for logging audit events."""

    @staticmethod
    async def log_event(
        db: AsyncSession,
        action: str,
        success: bool = True,
        user: User | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
        error_message: str | None = None,
        request: Request | None = None,
    ) -> AuditLog:
        """Log an audit event.

        Args:
            db: Database session
            action: Action performed (e.g., "backup_restore", "user_login")
            success: Whether the action was successful
            user: User who performed the action (None for system actions)
            resource_type: Type of resource affected (e.g., "backup", "vehicle")
            resource_id: ID of the resource
            details: Additional details about the action
            error_message: Error message if action failed
            request: FastAPI request object for extracting IP and user agent

        Returns:
            The created audit log entry
        """
        ip_address = None
        user_agent = None

        if request:
            # Extract IP address
            if hasattr(request, "client") and request.client:
                ip_address = request.client.host

            # Extract user agent
            user_agent = request.headers.get("user-agent")

        audit_entry = AuditLog(
            timestamp=datetime.now(UTC),
            user_id=user.id if user else None,
            username=user.username if user else "system",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details,
            success=1 if success else 0,
            error_message=error_message,
        )

        db.add(audit_entry)
        await db.commit()
        await db.refresh(audit_entry)

        logger.info(
            f"Audit log: {action} by {audit_entry.username} "
            f"(success={success}, resource={resource_type}:{resource_id})"
        )

        return audit_entry

    @staticmethod
    async def log_backup_created(
        db: AsyncSession,
        filename: str,
        backup_type: str,
        user: User | None = None,
        request: Request | None = None,
    ):
        """Log backup creation."""
        await AuditLogger.log_event(
            db=db,
            action="backup_created",
            user=user,
            resource_type="backup",
            resource_id=filename,
            details={"backup_type": backup_type},
            request=request,
        )

    @staticmethod
    async def log_backup_restored(
        db: AsyncSession,
        filename: str,
        backup_type: str,
        user: User | None = None,
        request: Request | None = None,
    ):
        """Log backup restoration."""
        await AuditLogger.log_event(
            db=db,
            action="backup_restored",
            user=user,
            resource_type="backup",
            resource_id=filename,
            details={"backup_type": backup_type},
            request=request,
        )

    @staticmethod
    async def log_backup_deleted(
        db: AsyncSession,
        filename: str,
        user: User | None = None,
        request: Request | None = None,
    ):
        """Log backup deletion."""
        await AuditLogger.log_event(
            db=db,
            action="backup_deleted",
            user=user,
            resource_type="backup",
            resource_id=filename,
            request=request,
        )

    @staticmethod
    async def log_user_login(
        db: AsyncSession,
        user: User,
        success: bool = True,
        error_message: str | None = None,
        request: Request | None = None,
    ):
        """Log user login attempt."""
        await AuditLogger.log_event(
            db=db,
            action="user_login",
            success=success,
            user=user if success else None,
            resource_type="authentication",
            error_message=error_message,
            request=request,
        )

    @staticmethod
    async def log_user_logout(
        db: AsyncSession,
        user: User,
        request: Request | None = None,
    ):
        """Log user logout."""
        await AuditLogger.log_event(
            db=db,
            action="user_logout",
            user=user,
            resource_type="authentication",
            request=request,
        )

    @staticmethod
    async def log_password_change(
        db: AsyncSession,
        user: User,
        request: Request | None = None,
    ):
        """Log password change."""
        await AuditLogger.log_event(
            db=db,
            action="password_changed",
            user=user,
            resource_type="user",
            resource_id=str(user.id),
            request=request,
        )

    @staticmethod
    async def log_user_created(
        db: AsyncSession,
        created_user: User,
        creator: User | None = None,
        request: Request | None = None,
    ):
        """Log user creation."""
        await AuditLogger.log_event(
            db=db,
            action="user_created",
            user=creator,
            resource_type="user",
            resource_id=str(created_user.id),
            details={"username": created_user.username, "email": created_user.email},
            request=request,
        )

    @staticmethod
    async def log_user_deleted(
        db: AsyncSession,
        deleted_user: User,
        deleter: User,
        request: Request | None = None,
    ):
        """Log user deletion."""
        await AuditLogger.log_event(
            db=db,
            action="user_deleted",
            user=deleter,
            resource_type="user",
            resource_id=str(deleted_user.id),
            details={"username": deleted_user.username},
            request=request,
        )

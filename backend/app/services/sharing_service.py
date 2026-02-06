"""Vehicle sharing service for granting vehicle access to other users."""

# pyright: reportOptionalOperand=false, reportReturnType=false

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_share import VehicleShare
from app.schemas.family import (
    ShareableUser,
    VehicleShareCreate,
    VehicleShareResponse,
    VehicleShareUpdate,
)
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


class SharingService:
    """Service for managing vehicle sharing."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def share_vehicle(
        self,
        vin: str,
        share_request: VehicleShareCreate,
        current_user: User,
    ) -> VehicleShareResponse:
        """
        Share a vehicle with another user.

        Only the owner or an admin can share a vehicle.

        Args:
            vin: Vehicle VIN to share
            share_request: Share details (user_id, permission)
            current_user: User performing the share (owner or admin)

        Returns:
            VehicleShareResponse with share details

        Raises:
            HTTPException 403: If user is not owner or admin
            HTTPException 404: If vehicle or recipient not found
            HTTPException 400: If sharing with self, owner, or disabled user
            HTTPException 409: If share already exists
        """
        try:
            # Get the vehicle
            result = await self.db.execute(select(Vehicle).where(Vehicle.vin == vin))
            vehicle = result.scalar_one_or_none()

            if not vehicle:
                raise HTTPException(status_code=404, detail="Vehicle not found")

            # Check authorization (owner or admin)
            if not current_user.is_admin and vehicle.user_id != current_user.id:
                raise HTTPException(
                    status_code=403,
                    detail="Only the owner or an admin can share this vehicle",
                )

            # Get the recipient user
            result = await self.db.execute(select(User).where(User.id == share_request.user_id))
            recipient = result.scalar_one_or_none()

            if not recipient:
                raise HTTPException(status_code=404, detail="Recipient user not found")

            if not recipient.is_active:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot share with disabled user",
                )

            if recipient.id == current_user.id:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot share with yourself",
                )

            if recipient.id == vehicle.user_id:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot share with the owner",
                )

            # Check if share already exists
            result = await self.db.execute(
                select(VehicleShare).where(
                    VehicleShare.vehicle_vin == vin,
                    VehicleShare.user_id == recipient.id,
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                raise HTTPException(
                    status_code=409,
                    detail="Share already exists for this user",
                )

            # Create share
            share = VehicleShare(
                vehicle_vin=vin,
                user_id=recipient.id,
                permission=share_request.permission,
                shared_by=current_user.id,
                shared_at=datetime.now(UTC),
            )
            self.db.add(share)

            await self.db.commit()
            await self.db.refresh(share)

            logger.info(
                "Vehicle %s shared with user %s (permission: %s) by user %s",
                vin,
                recipient.username,
                share_request.permission,
                current_user.username,
            )

            return VehicleShareResponse(
                id=share.id,
                vehicle_vin=share.vehicle_vin,
                user=recipient,
                permission=share.permission,
                shared_by=current_user,
                shared_at=share.shared_at,
            )

        except IntegrityError as e:
            await self.db.rollback()
            logger.error("Integrity error creating share: %s", sanitize_for_log(e))
            raise HTTPException(status_code=409, detail="Share already exists")

        except OperationalError as e:
            logger.error("Database error creating share: %s", sanitize_for_log(e))
            raise HTTPException(
                status_code=503,
                detail="Database temporarily unavailable",
            )

    async def update_share(
        self,
        share_id: int,
        update_request: VehicleShareUpdate,
        current_user: User,
    ) -> VehicleShareResponse:
        """
        Update share permission level.

        Only the owner or an admin can update shares.

        Args:
            share_id: Share ID to update
            update_request: New permission level
            current_user: User performing the update

        Returns:
            Updated VehicleShareResponse

        Raises:
            HTTPException 403: If user is not owner or admin
            HTTPException 404: If share not found
        """
        try:
            # Get the share with vehicle
            result = await self.db.execute(select(VehicleShare).where(VehicleShare.id == share_id))
            share = result.scalar_one_or_none()

            if not share:
                raise HTTPException(status_code=404, detail="Share not found")

            # Get the vehicle for authorization check
            result = await self.db.execute(select(Vehicle).where(Vehicle.vin == share.vehicle_vin))
            vehicle = result.scalar_one_or_none()

            # Check authorization (owner or admin)
            if not current_user.is_admin and (not vehicle or vehicle.user_id != current_user.id):
                raise HTTPException(
                    status_code=403,
                    detail="Only the owner or an admin can update this share",
                )

            # Update permission
            share.permission = update_request.permission

            await self.db.commit()
            await self.db.refresh(share)

            # Get user details for response
            result = await self.db.execute(select(User).where(User.id == share.user_id))
            shared_user = result.scalar_one_or_none()

            result = await self.db.execute(select(User).where(User.id == share.shared_by))
            shared_by_user = result.scalar_one_or_none()

            logger.info(
                "Share %s permission updated to %s by user %s",
                share_id,
                update_request.permission,
                current_user.username,
            )

            return VehicleShareResponse(
                id=share.id,
                vehicle_vin=share.vehicle_vin,
                user=shared_user,
                permission=share.permission,
                shared_by=shared_by_user,
                shared_at=share.shared_at,
            )

        except OperationalError as e:
            logger.error("Database error updating share: %s", sanitize_for_log(e))
            raise HTTPException(
                status_code=503,
                detail="Database temporarily unavailable",
            )

    async def revoke_share(
        self,
        share_id: int,
        current_user: User,
    ) -> None:
        """
        Revoke (delete) a vehicle share.

        Only the owner or an admin can revoke shares.

        Args:
            share_id: Share ID to revoke
            current_user: User performing the revocation

        Raises:
            HTTPException 403: If user is not owner or admin
            HTTPException 404: If share not found
        """
        try:
            # Get the share
            result = await self.db.execute(select(VehicleShare).where(VehicleShare.id == share_id))
            share = result.scalar_one_or_none()

            if not share:
                raise HTTPException(status_code=404, detail="Share not found")

            # Get the vehicle for authorization check
            result = await self.db.execute(select(Vehicle).where(Vehicle.vin == share.vehicle_vin))
            vehicle = result.scalar_one_or_none()

            # Check authorization (owner or admin)
            if not current_user.is_admin and (not vehicle or vehicle.user_id != current_user.id):
                raise HTTPException(
                    status_code=403,
                    detail="Only the owner or an admin can revoke this share",
                )

            # Delete the share
            await self.db.execute(delete(VehicleShare).where(VehicleShare.id == share_id))
            await self.db.commit()

            logger.info(
                "Share %s revoked by user %s",
                share_id,
                current_user.username,
            )

        except OperationalError as e:
            logger.error("Database error revoking share: %s", sanitize_for_log(e))
            raise HTTPException(
                status_code=503,
                detail="Database temporarily unavailable",
            )

    async def get_vehicle_shares(
        self,
        vin: str,
        current_user: User,
    ) -> tuple[list[VehicleShareResponse], int]:
        """
        Get all shares for a vehicle.

        Only the owner or an admin can see shares.

        Args:
            vin: Vehicle VIN
            current_user: User requesting the list

        Returns:
            Tuple of (shares list, total count)

        Raises:
            HTTPException 403: If user is not owner or admin
            HTTPException 404: If vehicle not found
        """
        try:
            # Get the vehicle
            result = await self.db.execute(select(Vehicle).where(Vehicle.vin == vin))
            vehicle = result.scalar_one_or_none()

            if not vehicle:
                raise HTTPException(status_code=404, detail="Vehicle not found")

            # Check authorization (owner or admin)
            if not current_user.is_admin and vehicle.user_id != current_user.id:
                raise HTTPException(
                    status_code=403,
                    detail="Only the owner or an admin can view shares",
                )

            # Get shares
            result = await self.db.execute(
                select(VehicleShare)
                .where(VehicleShare.vehicle_vin == vin)
                .order_by(VehicleShare.shared_at.desc())
            )
            shares = result.scalars().all()

            # Build responses with user details
            responses = []
            for share in shares:
                result = await self.db.execute(select(User).where(User.id == share.user_id))
                shared_user = result.scalar_one_or_none()

                result = await self.db.execute(select(User).where(User.id == share.shared_by))
                shared_by_user = result.scalar_one_or_none()

                responses.append(
                    VehicleShareResponse(
                        id=share.id,
                        vehicle_vin=share.vehicle_vin,
                        user=shared_user,
                        permission=share.permission,
                        shared_by=shared_by_user,
                        shared_at=share.shared_at,
                    )
                )

            return responses, len(responses)

        except OperationalError as e:
            logger.error("Database error getting shares: %s", sanitize_for_log(e))
            raise HTTPException(
                status_code=503,
                detail="Database temporarily unavailable",
            )

    async def get_shareable_users(
        self,
        current_user: User,
    ) -> list[ShareableUser]:
        """
        Get list of users available for sharing.

        Returns minimal user info (id, display_name, relationship).
        Excludes current user and disabled users.

        Args:
            current_user: The requesting user

        Returns:
            List of ShareableUser
        """
        try:
            result = await self.db.execute(
                select(User)
                .where(
                    User.is_active == True,  # noqa: E712
                    User.id != current_user.id,
                )
                .order_by(User.username)
            )
            users = result.scalars().all()

            return [
                ShareableUser(
                    id=user.id,
                    display_name=user.full_name or user.username,
                    relationship=user.relationship,
                )
                for user in users
            ]

        except OperationalError as e:
            logger.error("Database error getting shareable users: %s", sanitize_for_log(e))
            raise HTTPException(
                status_code=503,
                detail="Database temporarily unavailable",
            )

    async def check_share_permission(
        self,
        vin: str,
        user_id: int,
    ) -> str | None:
        """
        Check if a user has share access to a vehicle.

        Args:
            vin: Vehicle VIN
            user_id: User ID to check

        Returns:
            'read', 'write', or None if no share exists
        """
        try:
            result = await self.db.execute(
                select(VehicleShare).where(
                    VehicleShare.vehicle_vin == vin,
                    VehicleShare.user_id == user_id,
                )
            )
            share = result.scalar_one_or_none()

            if share:
                return share.permission
            return None

        except OperationalError:
            return None

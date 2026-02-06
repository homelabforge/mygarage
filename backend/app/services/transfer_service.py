"""Vehicle transfer service for ownership transfers between users."""

# pyright: reportOptionalOperand=false, reportReturnType=false

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_share import VehicleShare
from app.models.vehicle_transfer import VehicleTransfer
from app.schemas.family import (
    EligibleRecipient,
    VehicleTransferRequest,
    VehicleTransferResponse,
)
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


class TransferService:
    """Service for managing vehicle ownership transfers."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def transfer_vehicle(
        self,
        vin: str,
        transfer_request: VehicleTransferRequest,
        current_user: User,
    ) -> VehicleTransferResponse:
        """
        Transfer vehicle ownership from one user to another.

        This is an admin-only operation. The transfer:
        1. Updates vehicle.user_id to the new owner
        2. Creates an audit record in vehicle_transfers
        3. Removes any existing share for the new owner (they now own it)

        Args:
            vin: Vehicle VIN to transfer
            transfer_request: Transfer details (to_user_id, notes, data_included)
            current_user: Admin performing the transfer

        Returns:
            VehicleTransferResponse with transfer details

        Raises:
            HTTPException 403: If current_user is not admin
            HTTPException 404: If vehicle or recipient not found
            HTTPException 400: If recipient is current owner or disabled
        """
        # Verify admin
        if not current_user.is_admin:
            raise HTTPException(
                status_code=403,
                detail="Only admins can transfer vehicles",
            )

        try:
            # Get the vehicle
            result = await self.db.execute(select(Vehicle).where(Vehicle.vin == vin))
            vehicle = result.scalar_one_or_none()

            if not vehicle:
                raise HTTPException(status_code=404, detail="Vehicle not found")

            # Get current owner
            from_user_id = vehicle.user_id
            if from_user_id is None:
                raise HTTPException(
                    status_code=400,
                    detail="Vehicle has no current owner",
                )

            # Get the from_user for the audit record
            result = await self.db.execute(select(User).where(User.id == from_user_id))
            from_user = result.scalar_one_or_none()

            # Get the recipient user
            result = await self.db.execute(
                select(User).where(User.id == transfer_request.to_user_id)
            )
            to_user = result.scalar_one_or_none()

            if not to_user:
                raise HTTPException(status_code=404, detail="Recipient user not found")

            if not to_user.is_active:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot transfer to disabled user",
                )

            if to_user.id == from_user_id:
                raise HTTPException(
                    status_code=400,
                    detail="Recipient is already the owner",
                )

            # Update vehicle ownership
            vehicle.user_id = to_user.id
            vehicle.updated_at = datetime.now(UTC)

            # Remove any existing share for the new owner (they now own it)
            await self.db.execute(
                delete(VehicleShare).where(
                    VehicleShare.vehicle_vin == vin,
                    VehicleShare.user_id == to_user.id,
                )
            )

            # Create audit record
            transfer = VehicleTransfer(
                vehicle_vin=vin,
                from_user_id=from_user_id,
                to_user_id=to_user.id,
                transferred_at=datetime.now(UTC),
                transferred_by=current_user.id,
                transfer_notes=transfer_request.transfer_notes,
                data_included=json.dumps(transfer_request.data_included),
            )
            self.db.add(transfer)

            await self.db.commit()
            await self.db.refresh(transfer)

            logger.info(
                "Vehicle %s transferred from user %s to user %s by admin %s",
                vin,
                from_user_id,
                to_user.id,
                current_user.username,
            )

            # Build response
            return VehicleTransferResponse(
                id=transfer.id,
                vehicle_vin=transfer.vehicle_vin,
                from_user=from_user,
                to_user=to_user,
                transferred_at=transfer.transferred_at,
                transferred_by=current_user,
                transfer_notes=transfer.transfer_notes,
                data_included=json.loads(transfer.data_included)
                if transfer.data_included
                else None,
            )

        except OperationalError as e:
            logger.error("Database error during transfer: %s", sanitize_for_log(e))
            raise HTTPException(
                status_code=503,
                detail="Database temporarily unavailable",
            )

    async def get_transfer_history(
        self,
        vin: str,
    ) -> tuple[list[VehicleTransferResponse], int]:
        """
        Get transfer history for a vehicle.

        Args:
            vin: Vehicle VIN

        Returns:
            Tuple of (transfers list, total count)
        """
        try:
            # Get transfers ordered by date descending
            result = await self.db.execute(
                select(VehicleTransfer)
                .where(VehicleTransfer.vehicle_vin == vin)
                .order_by(VehicleTransfer.transferred_at.desc())
            )
            transfers = result.scalars().all()

            # Build responses with user details
            responses = []
            for transfer in transfers:
                # Get user details
                from_result = await self.db.execute(
                    select(User).where(User.id == transfer.from_user_id)
                )
                from_user = from_result.scalar_one_or_none()

                to_result = await self.db.execute(
                    select(User).where(User.id == transfer.to_user_id)
                )
                to_user = to_result.scalar_one_or_none()

                by_result = await self.db.execute(
                    select(User).where(User.id == transfer.transferred_by)
                )
                by_user = by_result.scalar_one_or_none()

                responses.append(
                    VehicleTransferResponse(
                        id=transfer.id,
                        vehicle_vin=transfer.vehicle_vin,
                        from_user=from_user,
                        to_user=to_user,
                        transferred_at=transfer.transferred_at,
                        transferred_by=by_user,
                        transfer_notes=transfer.transfer_notes,
                        data_included=json.loads(transfer.data_included)
                        if transfer.data_included
                        else None,
                    )
                )

            return responses, len(responses)

        except OperationalError as e:
            logger.error("Database error getting transfer history: %s", sanitize_for_log(e))
            raise HTTPException(
                status_code=503,
                detail="Database temporarily unavailable",
            )

    async def get_eligible_recipients(
        self,
        vin: str,
        current_user: User,
    ) -> list[EligibleRecipient]:
        """
        Get list of users eligible to receive a vehicle transfer.

        Returns active users excluding the current owner.

        Args:
            vin: Vehicle VIN
            current_user: Admin requesting the list

        Returns:
            List of eligible recipient users
        """
        # Verify admin
        if not current_user.is_admin:
            raise HTTPException(
                status_code=403,
                detail="Only admins can view eligible recipients",
            )

        try:
            # Get the vehicle to find current owner
            result = await self.db.execute(select(Vehicle).where(Vehicle.vin == vin))
            vehicle = result.scalar_one_or_none()

            if not vehicle:
                raise HTTPException(status_code=404, detail="Vehicle not found")

            current_owner_id = vehicle.user_id

            # Get active users excluding current owner
            query = select(User).where(
                User.is_active == True,  # noqa: E712
            )
            if current_owner_id:
                query = query.where(User.id != current_owner_id)

            result = await self.db.execute(query.order_by(User.username))
            users = result.scalars().all()

            return [
                EligibleRecipient(
                    id=user.id,
                    username=user.username,
                    full_name=user.full_name,
                    relationship=user.relationship,
                )
                for user in users
            ]

        except OperationalError as e:
            logger.error("Database error getting eligible recipients: %s", sanitize_for_log(e))
            raise HTTPException(
                status_code=503,
                detail="Database temporarily unavailable",
            )

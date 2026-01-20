"""Vehicle business logic service layer."""

# pyright: reportArgumentType=false, reportOptionalOperand=false, reportGeneralTypeIssues=false, reportReturnType=false

import logging
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select, delete, func
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle
from app.models.user import User
from app.schemas.vehicle import VehicleCreate, VehicleUpdate
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


class VehicleService:
    """Service for managing vehicle business logic."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_vehicles(
        self, current_user: Optional[User], skip: int = 0, limit: int = 100
    ) -> tuple[list[Vehicle], int]:
        """
        Get list of vehicles for the current user.

        Args:
            current_user: The authenticated user (None if auth_mode='none')
            skip: Number of records to skip (pagination)
            limit: Maximum number of records to return

        Returns:
            Tuple of (vehicles list, total count)
        """
        try:
            # Build query with ownership filter
            query = select(Vehicle).order_by(Vehicle.created_at.desc())

            # If auth is disabled, show all vehicles
            # Non-admin users can only see their own vehicles
            if current_user is not None and not current_user.is_admin:
                query = query.where(Vehicle.user_id == current_user.id)

            # Get vehicles with pagination
            result = await self.db.execute(query.offset(skip).limit(limit))
            vehicles = list(result.scalars().all())

            # Get total count with same filter
            count_query = select(func.count()).select_from(Vehicle)
            if current_user is not None and not current_user.is_admin:
                count_query = count_query.where(Vehicle.user_id == current_user.id)

            count_result = await self.db.execute(count_query)
            total = count_result.scalar()

            return vehicles, total

        except OperationalError as e:
            logger.error(
                "Database connection error listing vehicles: %s", sanitize_for_log(e)
            )
            raise HTTPException(
                status_code=503, detail="Database temporarily unavailable"
            )

    async def get_vehicle(self, vin: str, current_user: Optional[User]) -> Vehicle:
        """
        Get a specific vehicle by VIN with ownership check.

        Args:
            vin: Vehicle VIN
            current_user: The authenticated user

        Returns:
            Vehicle object

        Raises:
            HTTPException: 404 if not found, 403 if not authorized
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        vehicle = await get_vehicle_or_403(vin, current_user, self.db)
        return vehicle

    async def create_vehicle(
        self, vehicle_data: VehicleCreate, current_user: Optional[User]
    ) -> Vehicle:
        """
        Create a new vehicle.

        Args:
            vehicle_data: Vehicle creation data
            current_user: The authenticated user (will be assigned as owner, None if auth_mode='none')

        Returns:
            Created Vehicle object

        Raises:
            HTTPException: 400 if VIN already exists
        """
        try:
            # Check if VIN already exists
            result = await self.db.execute(
                select(Vehicle).where(Vehicle.vin == vehicle_data.vin)
            )
            existing = result.scalar_one_or_none()

            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Vehicle with VIN {vehicle_data.vin} already exists",
                )

            # Create vehicle with ownership assigned to current user
            vehicle_dict = vehicle_data.model_dump()
            if current_user is not None:
                vehicle_dict["user_id"] = current_user.id  # Assign ownership
                username = current_user.username
            else:
                username = "guest"

            vehicle = Vehicle(**vehicle_dict)
            self.db.add(vehicle)
            await self.db.commit()
            await self.db.refresh(vehicle)

            logger.info(
                "Created vehicle: %s (%s) for user %s",
                sanitize_for_log(vehicle.vin),
                sanitize_for_log(vehicle.nickname),
                sanitize_for_log(username),
            )

            return vehicle

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation creating vehicle: %s",
                sanitize_for_log(e),
            )
            raise HTTPException(
                status_code=409,
                detail=f"Vehicle with VIN {vehicle_data.vin} already exists",
            )
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error creating vehicle: %s", sanitize_for_log(e)
            )
            raise HTTPException(
                status_code=503, detail="Database temporarily unavailable"
            )

    async def update_vehicle(
        self, vin: str, vehicle_data: VehicleUpdate, current_user: User
    ) -> Vehicle:
        """
        Update an existing vehicle.

        Args:
            vin: Vehicle VIN
            vehicle_data: Vehicle update data
            current_user: The authenticated user

        Returns:
            Updated Vehicle object

        Raises:
            HTTPException: 404 if not found, 403 if not authorized
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            # Get vehicle with ownership check
            vehicle = await get_vehicle_or_403(vin, current_user, self.db)

            # Update fields (only non-None values)
            update_data = vehicle_data.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                setattr(vehicle, field, value)

            await self.db.commit()
            await self.db.refresh(vehicle)

            logger.info("Updated vehicle: %s", sanitize_for_log(vehicle.vin))

            return vehicle

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation updating vehicle %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Database constraint violation")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error updating vehicle %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(
                status_code=503, detail="Database temporarily unavailable"
            )

    async def delete_vehicle(self, vin: str, current_user: User) -> None:
        """
        Delete a vehicle.

        Args:
            vin: Vehicle VIN
            current_user: The authenticated user

        Raises:
            HTTPException: 404 if not found, 403 if not authorized
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            # Get vehicle with ownership check
            _ = await get_vehicle_or_403(vin, current_user, self.db)

            # Delete vehicle (cascade will handle related records)
            await self.db.execute(delete(Vehicle).where(Vehicle.vin == vin))
            await self.db.commit()

            logger.info("Deleted vehicle: %s", sanitize_for_log(vin))

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation deleting vehicle %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(
                status_code=409, detail="Cannot delete vehicle with dependent records"
            )
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error deleting vehicle %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(
                status_code=503, detail="Database temporarily unavailable"
            )

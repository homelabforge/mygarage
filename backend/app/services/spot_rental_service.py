"""Spot rental business logic service layer."""

import logging

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import SpotRental
from app.models.spot_rental_billing import SpotRentalBilling
from app.models.user import User
from app.schemas.spot_rental import (
    SpotRentalCreate,
    SpotRentalListResponse,
    SpotRentalResponse,
    SpotRentalUpdate,
)
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


class SpotRentalService:
    """Service for managing spot rental business logic."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_rentals(
        self,
        vin: str,
        current_user: User,
    ) -> SpotRentalListResponse:
        """Get all spot rentals for a vehicle.

        Args:
            vin: Vehicle identification number.
            current_user: Authenticated user.

        Returns:
            SpotRentalListResponse with rentals and total count.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)

            query = (
                select(SpotRental)
                .where(SpotRental.vin == vin)
                .options(selectinload(SpotRental.billings))
                .order_by(SpotRental.check_in_date.desc())
            )
            result = await self.db.execute(query)
            rentals = result.scalars().all()

            count_result = await self.db.execute(
                select(func.count()).select_from(SpotRental).where(SpotRental.vin == vin)
            )
            total = count_result.scalar_one()

            return SpotRentalListResponse(
                spot_rentals=[SpotRentalResponse.model_validate(r) for r in rentals],
                total=total,
            )

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error listing spot rentals for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def get_rental(
        self,
        vin: str,
        rental_id: int,
        current_user: User,
    ) -> SpotRentalResponse:
        """Get a specific spot rental by ID.

        Args:
            vin: Vehicle identification number.
            rental_id: Spot rental record ID.
            current_user: Authenticated user.

        Returns:
            SpotRentalResponse for the requested rental.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)

            result = await self.db.execute(
                select(SpotRental)
                .where(SpotRental.id == rental_id, SpotRental.vin == vin)
                .options(selectinload(SpotRental.billings))
            )
            rental = result.scalar_one_or_none()

            if not rental:
                raise HTTPException(status_code=404, detail="Spot rental not found")

            return SpotRentalResponse.model_validate(rental)

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error getting spot rental %s for %s: %s",
                rental_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def create_rental(
        self,
        vin: str,
        data: SpotRentalCreate,
        current_user: User,
    ) -> SpotRentalResponse:
        """Create a new spot rental record.

        Includes vehicle type validation (only RV/FifthWheel) and auto-billing
        entry creation when a monthly rate is provided.

        Args:
            vin: Vehicle identification number.
            data: Spot rental creation data.
            current_user: Authenticated user.

        Returns:
            SpotRentalResponse for the newly created rental.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            vehicle = await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            # Verify vehicle is RV or Fifth Wheel
            vehicle_type = (vehicle.vehicle_type or "").replace(" ", "").lower()
            if vehicle_type not in {"rv", "fifthwheel"}:
                raise HTTPException(
                    status_code=400,
                    detail="Spot rentals are only available for RVs and Fifth Wheels",
                )

            rental = SpotRental(
                vin=vin,
                location_name=data.location_name,
                location_address=data.location_address,
                check_in_date=data.check_in_date,
                check_out_date=data.check_out_date,
                nightly_rate=data.nightly_rate,
                weekly_rate=data.weekly_rate,
                monthly_rate=data.monthly_rate,
                electric=data.electric,
                water=data.water,
                waste=data.waste,
                total_cost=data.total_cost,
                amenities=data.amenities,
                notes=data.notes,
            )

            self.db.add(rental)
            await self.db.commit()
            await self.db.refresh(rental)

            # Auto-create first billing entry if monthly rate is provided
            if data.monthly_rate is not None and data.monthly_rate > 0:
                billing_total = data.monthly_rate
                if data.electric:
                    billing_total += data.electric
                if data.water:
                    billing_total += data.water
                if data.waste:
                    billing_total += data.waste

                billing = SpotRentalBilling(
                    spot_rental_id=rental.id,
                    billing_date=data.check_in_date,
                    monthly_rate=data.monthly_rate,
                    electric=data.electric,
                    water=data.water,
                    waste=data.waste,
                    total=billing_total,
                    notes="Initial billing entry (auto-created)",
                )
                self.db.add(billing)
                await self.db.commit()

            # Eager-load billings relationship to avoid lazy-load issues
            await self.db.refresh(rental, attribute_names=["billings"])

            logger.info(
                "Created spot rental %s for vehicle %s",
                rental.id,
                sanitize_for_log(vin),
            )

            return SpotRentalResponse.model_validate(rental)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation creating spot rental for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Duplicate or invalid spot rental")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error creating spot rental for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def update_rental(
        self,
        vin: str,
        rental_id: int,
        data: SpotRentalUpdate,
        current_user: User,
    ) -> SpotRentalResponse:
        """Update an existing spot rental record.

        Args:
            vin: Vehicle identification number.
            rental_id: Spot rental record ID.
            data: Spot rental update data.
            current_user: Authenticated user.

        Returns:
            SpotRentalResponse for the updated rental.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(SpotRental)
                .where(SpotRental.id == rental_id, SpotRental.vin == vin)
                .options(selectinload(SpotRental.billings))
            )
            rental = result.scalar_one_or_none()

            if not rental:
                raise HTTPException(status_code=404, detail="Spot rental not found")

            # Update fields
            if data.location_name is not None:
                rental.location_name = data.location_name
            if data.location_address is not None:
                rental.location_address = data.location_address
            if data.check_in_date is not None:
                rental.check_in_date = data.check_in_date
            if data.check_out_date is not None:
                rental.check_out_date = data.check_out_date
            if data.nightly_rate is not None:
                rental.nightly_rate = data.nightly_rate
            if data.weekly_rate is not None:
                rental.weekly_rate = data.weekly_rate
            if data.monthly_rate is not None:
                rental.monthly_rate = data.monthly_rate
            if data.electric is not None:
                rental.electric = data.electric
            if data.water is not None:
                rental.water = data.water
            if data.waste is not None:
                rental.waste = data.waste
            if data.total_cost is not None:
                rental.total_cost = data.total_cost
            if data.amenities is not None:
                rental.amenities = data.amenities
            if data.notes is not None:
                rental.notes = data.notes

            await self.db.commit()
            await self.db.refresh(rental, attribute_names=["billings"])

            logger.info(
                "Updated spot rental %s for vehicle %s",
                rental_id,
                sanitize_for_log(vin),
            )

            return SpotRentalResponse.model_validate(rental)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation updating spot rental %s for %s: %s",
                rental_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Database constraint violation")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error updating spot rental %s for %s: %s",
                rental_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def delete_rental(
        self,
        vin: str,
        rental_id: int,
        current_user: User,
    ) -> None:
        """Delete a spot rental record.

        Args:
            vin: Vehicle identification number.
            rental_id: Spot rental record ID.
            current_user: Authenticated user.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(SpotRental).where(SpotRental.id == rental_id, SpotRental.vin == vin)
            )
            rental = result.scalar_one_or_none()

            if not rental:
                raise HTTPException(status_code=404, detail="Spot rental not found")

            await self.db.execute(
                delete(SpotRental).where(SpotRental.id == rental_id, SpotRental.vin == vin)
            )
            await self.db.commit()

            logger.info(
                "Deleted spot rental %s for vehicle %s",
                rental_id,
                sanitize_for_log(vin),
            )

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation deleting spot rental %s for %s: %s",
                rental_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Cannot delete rental with dependent data")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error deleting spot rental %s for %s: %s",
                rental_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

"""Fuel record business logic service layer with MPG calculation."""

# pyright: reportReturnType=false, reportOptionalOperand=false

import logging
from datetime import date as date_type
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fuel import FuelRecord
from app.models.user import User
from app.schemas.fuel import FuelRecordCreate, FuelRecordResponse, FuelRecordUpdate
from app.utils.cache import cached, invalidate_cache_for_vehicle
from app.utils.logging_utils import sanitize_for_log
from app.utils.odometer_sync import sync_odometer_from_record

logger = logging.getLogger(__name__)


def calculate_mpg(current_record: FuelRecord, previous_record: FuelRecord | None) -> Decimal | None:
    """
    Calculate MPG for a fuel record.

    Logic:
    - Only calculate for full tank fill-ups
    - Skip if no previous full tank fill-up
    - Skip if no mileage recorded
    - MPG = (current_mileage - previous_mileage) / current_gallons

    This follows the lubelog pattern for MPG calculation.
    """
    # Only calculate MPG for full tank fill-ups
    if not current_record.is_full_tank:
        return None

    # Need mileage and gallons
    if not current_record.mileage or not current_record.gallons:
        return None

    # Need a previous record to calculate distance
    if not previous_record or not previous_record.mileage:
        return None

    # Calculate miles driven
    miles_driven = current_record.mileage - previous_record.mileage

    # Sanity check
    if miles_driven <= 0 or current_record.gallons <= 0:
        return None

    # Calculate MPG
    mpg = Decimal(miles_driven) / current_record.gallons
    return round(mpg, 2)


async def get_previous_full_tank(
    db: AsyncSession, vin: str, current_date: date_type, current_mileage: int | None
) -> FuelRecord | None:
    """
    Get the most recent previous full tank fill-up.

    Used for MPG calculation - we need the last full tank to know how far we traveled.
    """
    query = (
        select(FuelRecord)
        .where(FuelRecord.vin == vin)
        .where(FuelRecord.is_full_tank.is_(True))
        .where(FuelRecord.date < current_date)
    )

    if current_mileage:
        query = query.where(FuelRecord.mileage < current_mileage)

    query = query.order_by(FuelRecord.date.desc()).limit(1)

    result = await db.execute(query)
    return result.scalar_one_or_none()


@cached(ttl_seconds=300)  # Cache for 5 minutes
async def calculate_average_mpg(
    db: AsyncSession, vin: str, exclude_hauling: bool = True
) -> Decimal | None:
    """
    Calculate average MPG across all fuel records with MPG data.

    Args:
        db: Database session
        vin: Vehicle VIN
        exclude_hauling: If True (default), exclude records where is_hauling=True for more accurate daily MPG

    Note: Results are cached for 5 minutes to improve performance.
    Cache is invalidated when fuel records are created/updated/deleted.
    """
    query = (
        select(FuelRecord)
        .where(FuelRecord.vin == vin)
        .where(FuelRecord.is_full_tank.is_(True))
        .where(FuelRecord.mileage.isnot(None))
        .where(FuelRecord.gallons.isnot(None))
    )

    # Optionally exclude hauling records for normal MPG calculation
    if exclude_hauling:
        query = query.where(FuelRecord.is_hauling.is_(False))

    query = query.order_by(FuelRecord.date)

    result = await db.execute(query)
    records = result.scalars().all()

    if len(records) < 2:
        return None

    mpg_values = []
    for i in range(1, len(records)):
        mpg = calculate_mpg(records[i], records[i - 1])
        if mpg:
            mpg_values.append(mpg)

    if not mpg_values:
        return None

    return round(sum(mpg_values) / len(mpg_values), 2)


class FuelRecordService:
    """Service for managing fuel record business logic with MPG calculations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_fuel_records(
        self,
        vin: str,
        current_user: User,
        skip: int = 0,
        limit: int = 100,
        include_hauling: bool = False,
    ) -> tuple[list[FuelRecordResponse], int, Decimal | None]:
        """
        Get all fuel records for a vehicle with MPG calculations.

        Args:
            vin: Vehicle VIN
            current_user: The authenticated user
            skip: Number of records to skip (pagination)
            limit: Maximum number of records to return
            include_hauling: Include towing/hauling records in MPG calculation

        Returns:
            Tuple of (fuel record responses with MPG, total count, average MPG)

        Raises:
            HTTPException: 404 if vehicle not found, 403 if not authorized
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            # Check vehicle ownership (raises 403 if unauthorized)
            _ = await get_vehicle_or_403(vin, current_user, self.db)

            # Get fuel records
            result = await self.db.execute(
                select(FuelRecord)
                .where(FuelRecord.vin == vin)
                .order_by(FuelRecord.date.desc())
                .offset(skip)
                .limit(limit)
            )
            records = result.scalars().all()

            # Get all full tank records for this VIN to avoid N+1 queries
            full_tank_result = await self.db.execute(
                select(FuelRecord)
                .where(FuelRecord.vin == vin)
                .where(FuelRecord.is_full_tank.is_(True))
                .where(FuelRecord.mileage.isnot(None))
                .order_by(FuelRecord.date.asc())
            )
            full_tank_records = full_tank_result.scalars().all()

            # Calculate MPG for each record
            responses = []
            for record in records:
                mpg = None
                if record.is_full_tank and record.mileage:
                    # Find previous full tank from our pre-fetched list
                    prev_record = None
                    for ft_record in reversed(full_tank_records):
                        if ft_record.date < record.date and (
                            not record.mileage or ft_record.mileage < record.mileage
                        ):
                            prev_record = ft_record
                            break

                    if prev_record:
                        mpg = calculate_mpg(record, prev_record)

                # Build response
                record_dict = record.__dict__.copy()
                record_dict["mpg"] = mpg
                responses.append(FuelRecordResponse(**record_dict))

            # Get total count
            count_result = await self.db.execute(
                select(func.count()).select_from(FuelRecord).where(FuelRecord.vin == vin)
            )
            total = count_result.scalar()

            # Calculate average MPG
            avg_mpg = await calculate_average_mpg(self.db, vin, exclude_hauling=not include_hauling)

            return responses, total, avg_mpg

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error listing fuel records for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def get_fuel_record(
        self, vin: str, record_id: int, current_user: User
    ) -> tuple[FuelRecord, Decimal | None]:
        """
        Get a specific fuel record by ID with MPG calculation.

        Args:
            vin: Vehicle VIN
            record_id: Fuel record ID
            current_user: The authenticated user

        Returns:
            Tuple of (FuelRecord object, calculated MPG)

        Raises:
            HTTPException: 404 if not found, 403 if not authorized
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        # Check vehicle ownership (raises 403 if unauthorized)
        await get_vehicle_or_403(vin, current_user, self.db)

        result = await self.db.execute(
            select(FuelRecord).where(FuelRecord.id == record_id).where(FuelRecord.vin == vin)
        )
        record = result.scalar_one_or_none()

        if not record:
            raise HTTPException(status_code=404, detail=f"Fuel record {record_id} not found")

        # Calculate MPG
        mpg = None
        if record.is_full_tank:
            prev_record = await get_previous_full_tank(self.db, vin, record.date, record.mileage)
            mpg = calculate_mpg(record, prev_record)

        return record, mpg

    async def create_fuel_record(
        self, vin: str, record_data: FuelRecordCreate, current_user: User
    ) -> tuple[FuelRecord, Decimal | None]:
        """
        Create a new fuel record with MPG calculation.

        Args:
            vin: Vehicle VIN
            record_data: Fuel record creation data
            current_user: The authenticated user

        Returns:
            Tuple of (created FuelRecord object, calculated MPG)

        Raises:
            HTTPException: 404 if vehicle not found, 403 if not authorized
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            # Check vehicle ownership (raises 403 if unauthorized)
            _ = await get_vehicle_or_403(vin, current_user, self.db)

            # Create fuel record
            record_dict = record_data.model_dump()
            record_dict["vin"] = vin

            # Auto-calculate propane_gallons if tank data provided but gallons not
            if (
                record_dict.get("tank_size_lb") is not None
                and record_dict.get("tank_quantity") is not None
                and record_dict.get("propane_gallons") is None
            ):
                calculated = (
                    float(record_dict["tank_size_lb"]) / 4.24 * record_dict["tank_quantity"]
                )
                record_dict["propane_gallons"] = Decimal(str(round(calculated, 3)))

            record = FuelRecord(**record_dict)

            self.db.add(record)
            await self.db.commit()
            await self.db.refresh(record)

            # Calculate MPG
            mpg = None
            if record.is_full_tank:
                prev_record = await get_previous_full_tank(
                    self.db, vin, record.date, record.mileage
                )
                mpg = calculate_mpg(record, prev_record)

            logger.info(
                "Created fuel record %s for %s (MPG: %s)",
                record.id,
                sanitize_for_log(vin),
                mpg,
            )

            # Auto-sync odometer if mileage provided
            if record.date and record.mileage:
                try:
                    await sync_odometer_from_record(
                        db=self.db,
                        vin=vin,
                        date=record.date,
                        mileage=record.mileage,
                        source_type="fuel",
                        source_id=record.id,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to auto-sync odometer for fuel record %s: %s",
                        record.id,
                        sanitize_for_log(e),
                    )
                    # Don't fail the request if odometer sync fails

            # Invalidate analytics cache for this vehicle
            await invalidate_cache_for_vehicle(vin)

            return record, mpg

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation creating fuel record for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Duplicate or invalid fuel record")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error creating fuel record for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def update_fuel_record(
        self,
        vin: str,
        record_id: int,
        record_data: FuelRecordUpdate,
        current_user: User,
    ) -> tuple[FuelRecord, Decimal | None]:
        """
        Update an existing fuel record.

        Args:
            vin: Vehicle VIN
            record_id: Fuel record ID
            record_data: Fuel record update data
            current_user: The authenticated user

        Returns:
            Tuple of (updated FuelRecord object, calculated MPG)

        Raises:
            HTTPException: 404 if not found, 403 if not authorized
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            # Check vehicle ownership (raises 403 if unauthorized)
            await get_vehicle_or_403(vin, current_user, self.db)

            # Get existing record
            result = await self.db.execute(
                select(FuelRecord).where(FuelRecord.id == record_id).where(FuelRecord.vin == vin)
            )
            record = result.scalar_one_or_none()

            if not record:
                raise HTTPException(status_code=404, detail=f"Fuel record {record_id} not found")

            # Update fields
            update_data = record_data.model_dump(exclude_unset=True)

            # Auto-calculate propane_gallons if tank data provided/updated but gallons not
            if (
                update_data.get("tank_size_lb") is not None
                and update_data.get("tank_quantity") is not None
                and update_data.get("propane_gallons") is None
            ):
                # Check if we have both tank fields (either from update or existing record)
                tank_size = update_data.get("tank_size_lb", record.tank_size_lb)
                tank_qty = update_data.get("tank_quantity", record.tank_quantity)
                if tank_size is not None and tank_qty is not None:
                    calculated = float(tank_size) / 4.24 * tank_qty
                    update_data["propane_gallons"] = Decimal(str(round(calculated, 3)))

            for field, value in update_data.items():
                setattr(record, field, value)

            await self.db.commit()
            await self.db.refresh(record)

            # Calculate MPG
            mpg = None
            if record.is_full_tank:
                prev_record = await get_previous_full_tank(
                    self.db, vin, record.date, record.mileage
                )
                mpg = calculate_mpg(record, prev_record)

            logger.info("Updated fuel record %s for %s", record_id, sanitize_for_log(vin))

            # Auto-sync odometer if mileage and date are present
            if record.date and record.mileage:
                try:
                    await sync_odometer_from_record(
                        db=self.db,
                        vin=vin,
                        date=record.date,
                        mileage=record.mileage,
                        source_type="fuel",
                        source_id=record.id,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to auto-sync odometer for fuel record %s: %s",
                        record_id,
                        sanitize_for_log(e),
                    )
                    # Don't fail the request if odometer sync fails

            # Invalidate analytics cache for this vehicle
            await invalidate_cache_for_vehicle(vin)

            return record, mpg

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation updating fuel record %s for %s: %s",
                record_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Database constraint violation")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error updating fuel record %s for %s: %s",
                record_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def delete_fuel_record(self, vin: str, record_id: int, current_user: User) -> None:
        """
        Delete a fuel record.

        Args:
            vin: Vehicle VIN
            record_id: Fuel record ID
            current_user: The authenticated user

        Raises:
            HTTPException: 404 if not found, 403 if not authorized
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            # Check vehicle ownership (raises 403 if unauthorized)
            await get_vehicle_or_403(vin, current_user, self.db)

            # Check if record exists
            result = await self.db.execute(
                select(FuelRecord).where(FuelRecord.id == record_id).where(FuelRecord.vin == vin)
            )
            record = result.scalar_one_or_none()

            if not record:
                raise HTTPException(status_code=404, detail=f"Fuel record {record_id} not found")

            # Delete record
            await self.db.execute(
                delete(FuelRecord).where(FuelRecord.id == record_id).where(FuelRecord.vin == vin)
            )
            await self.db.commit()

            logger.info("Deleted fuel record %s for %s", record_id, sanitize_for_log(vin))

            # Invalidate analytics cache for this vehicle
            await invalidate_cache_for_vehicle(vin)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation deleting fuel record %s for %s: %s",
                record_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Cannot delete record with dependent data")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error deleting fuel record %s for %s: %s",
                record_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

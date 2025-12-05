"""Service record business logic service layer."""

import logging

from fastapi import HTTPException
from sqlalchemy import select, delete, func, outerjoin
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.service import ServiceRecord
from app.models.attachment import Attachment
from app.models.user import User
from app.schemas.service import ServiceRecordCreate, ServiceRecordUpdate, ServiceRecordResponse
from app.utils.cache import invalidate_cache_for_vehicle
from app.utils.odometer_sync import sync_odometer_from_record

logger = logging.getLogger(__name__)


class ServiceRecordService:
    """Service for managing service record business logic."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_service_records(
        self,
        vin: str,
        current_user: User,
        skip: int = 0,
        limit: int = 100
    ) -> tuple[list[ServiceRecordResponse], int]:
        """
        Get all service records for a vehicle with attachment counts.

        Args:
            vin: Vehicle VIN
            current_user: The authenticated user
            skip: Number of records to skip (pagination)
            limit: Maximum number of records to return

        Returns:
            Tuple of (service record responses, total count)

        Raises:
            HTTPException: 404 if vehicle not found, 403 if not authorized
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            # Check vehicle ownership (raises 403 if unauthorized)
            vehicle = await get_vehicle_or_403(vin, current_user, self.db)

            # Get service records with attachment counts in a single query
            # This avoids N+1 query problem by using LEFT JOIN and GROUP BY
            result = await self.db.execute(
                select(
                    ServiceRecord,
                    func.coalesce(func.count(Attachment.id), 0).label("attachment_count")
                )
                .select_from(
                    outerjoin(
                        ServiceRecord,
                        Attachment,
                        (ServiceRecord.id == Attachment.record_id) & (Attachment.record_type == "service")
                    )
                )
                .where(ServiceRecord.vin == vin)
                .group_by(ServiceRecord.id)
                .order_by(ServiceRecord.date.desc())
                .offset(skip)
                .limit(limit)
            )

            # Extract records and attachment counts from result
            records_with_counts = result.all()
            records = [row[0] for row in records_with_counts]
            attachment_counts = {row[0].id: row[1] for row in records_with_counts}

            # Get total count
            count_result = await self.db.execute(
                select(func.count()).select_from(ServiceRecord).where(ServiceRecord.vin == vin)
            )
            total = count_result.scalar()

            # Build response with attachment counts
            record_responses = []
            for record in records:
                record_dict = {
                    "id": record.id,
                    "vin": record.vin,
                    "date": record.date,
                    "mileage": record.mileage,
                    "description": record.description,
                    "cost": record.cost,
                    "notes": record.notes,
                    "vendor_name": record.vendor_name,
                    "vendor_location": record.vendor_location,
                    "service_type": record.service_type,
                    "insurance_claim": record.insurance_claim,
                    "created_at": record.created_at,
                    "attachment_count": attachment_counts.get(record.id, 0)
                }
                record_responses.append(ServiceRecordResponse(**record_dict))

            return record_responses, total

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error("Database connection error listing service records for %s: %s", vin, e)
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def get_service_record(
        self,
        vin: str,
        record_id: int,
        current_user: User
    ) -> ServiceRecord:
        """
        Get a specific service record by ID.

        Args:
            vin: Vehicle VIN
            record_id: Service record ID
            current_user: The authenticated user

        Returns:
            ServiceRecord object

        Raises:
            HTTPException: 404 if not found, 403 if not authorized
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        # Check vehicle ownership (raises 403 if unauthorized)
        await get_vehicle_or_403(vin, current_user, self.db)

        result = await self.db.execute(
            select(ServiceRecord)
            .where(ServiceRecord.id == record_id)
            .where(ServiceRecord.vin == vin)
        )
        record = result.scalar_one_or_none()

        if not record:
            raise HTTPException(status_code=404, detail=f"Service record {record_id} not found")

        return record

    async def create_service_record(
        self,
        vin: str,
        record_data: ServiceRecordCreate,
        current_user: User
    ) -> ServiceRecord:
        """
        Create a new service record.

        Args:
            vin: Vehicle VIN
            record_data: Service record creation data
            current_user: The authenticated user

        Returns:
            Created ServiceRecord object

        Raises:
            HTTPException: 404 if vehicle not found, 403 if not authorized
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            # Check vehicle ownership (raises 403 if unauthorized)
            vehicle = await get_vehicle_or_403(vin, current_user, self.db)

            # Create service record
            record_dict = record_data.model_dump()
            record_dict['vin'] = vin
            record = ServiceRecord(**record_dict)

            self.db.add(record)
            await self.db.commit()
            await self.db.refresh(record)

            logger.info("Created service record %s for %s", record.id, vin)

            # Auto-sync odometer if mileage provided
            if record.date and record.mileage:
                try:
                    await sync_odometer_from_record(
                        db=self.db,
                        vin=vin,
                        date=record.date,
                        mileage=record.mileage,
                        source_type="service",
                        source_id=record.id
                    )
                except Exception as e:
                    logger.warning("Failed to auto-sync odometer for service record %s: %s", record.id, e)
                    # Don't fail the request if odometer sync fails

            # Invalidate analytics cache for this vehicle
            await invalidate_cache_for_vehicle(vin)

            return record

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error("Database constraint violation creating service record for %s: %s", vin, e)
            raise HTTPException(status_code=409, detail="Duplicate or invalid service record")
        except OperationalError as e:
            await self.db.rollback()
            logger.error("Database connection error creating service record for %s: %s", vin, e)
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def update_service_record(
        self,
        vin: str,
        record_id: int,
        record_data: ServiceRecordUpdate,
        current_user: User
    ) -> ServiceRecord:
        """
        Update an existing service record.

        Args:
            vin: Vehicle VIN
            record_id: Service record ID
            record_data: Service record update data
            current_user: The authenticated user

        Returns:
            Updated ServiceRecord object

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
                select(ServiceRecord)
                .where(ServiceRecord.id == record_id)
                .where(ServiceRecord.vin == vin)
            )
            record = result.scalar_one_or_none()

            if not record:
                raise HTTPException(status_code=404, detail=f"Service record {record_id} not found")

            # Update fields
            update_data = record_data.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                setattr(record, field, value)

            await self.db.commit()
            await self.db.refresh(record)

            logger.info("Updated service record %s for %s", record_id, vin)

            # Auto-sync odometer if mileage and date are present
            if record.date and record.mileage:
                try:
                    await sync_odometer_from_record(
                        db=self.db,
                        vin=vin,
                        date=record.date,
                        mileage=record.mileage,
                        source_type="service",
                        source_id=record.id
                    )
                except Exception as e:
                    logger.warning("Failed to auto-sync odometer for service record %s: %s", record_id, e)
                    # Don't fail the request if odometer sync fails

            # Invalidate analytics cache for this vehicle
            await invalidate_cache_for_vehicle(vin)

            return record

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error("Database constraint violation updating service record %s for %s: %s", record_id, vin, e)
            raise HTTPException(status_code=409, detail="Database constraint violation")
        except OperationalError as e:
            await self.db.rollback()
            logger.error("Database connection error updating service record %s for %s: %s", record_id, vin, e)
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def delete_service_record(
        self,
        vin: str,
        record_id: int,
        current_user: User
    ) -> None:
        """
        Delete a service record.

        Args:
            vin: Vehicle VIN
            record_id: Service record ID
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
                select(ServiceRecord)
                .where(ServiceRecord.id == record_id)
                .where(ServiceRecord.vin == vin)
            )
            record = result.scalar_one_or_none()

            if not record:
                raise HTTPException(status_code=404, detail=f"Service record {record_id} not found")

            # Delete record
            await self.db.execute(
                delete(ServiceRecord)
                .where(ServiceRecord.id == record_id)
                .where(ServiceRecord.vin == vin)
            )
            await self.db.commit()

            logger.info("Deleted service record %s for %s", record_id, vin)

            # Invalidate analytics cache for this vehicle
            await invalidate_cache_for_vehicle(vin)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error("Database constraint violation deleting service record %s for %s: %s", record_id, vin, e)
            raise HTTPException(status_code=409, detail="Cannot delete record with dependent data")
        except OperationalError as e:
            await self.db.rollback()
            logger.error("Database connection error deleting service record %s for %s: %s", record_id, vin, e)
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

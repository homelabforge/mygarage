"""Warranty record business logic service layer."""

import logging

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import WarrantyRecord as WarrantyRecordModel
from app.models.user import User
from app.schemas.warranty import (
    WarrantyRecord,
    WarrantyRecordCreate,
    WarrantyRecordUpdate,
)
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


class WarrantyService:
    """Service for managing warranty record business logic."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_warranties(
        self,
        vin: str,
        current_user: User,
        skip: int = 0,
        limit: int = 100,
    ) -> list[WarrantyRecord]:
        """Get all warranty records for a vehicle.

        Returns:
            List of warranty record responses.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)

            result = await self.db.execute(
                select(WarrantyRecordModel)
                .where(WarrantyRecordModel.vin == vin)
                .order_by(WarrantyRecordModel.start_date.desc())
                .offset(skip)
                .limit(limit)
            )
            records = result.scalars().all()

            return [WarrantyRecord.model_validate(r) for r in records]

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error listing warranties for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def get_warranty(self, vin: str, warranty_id: int, current_user: User) -> WarrantyRecord:
        """Get a specific warranty record by ID."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()
        await get_vehicle_or_403(vin, current_user, self.db)

        result = await self.db.execute(
            select(WarrantyRecordModel).where(
                WarrantyRecordModel.vin == vin, WarrantyRecordModel.id == warranty_id
            )
        )
        record = result.scalar_one_or_none()

        if not record:
            raise HTTPException(status_code=404, detail=f"Warranty record {warranty_id} not found")

        return WarrantyRecord.model_validate(record)

    async def create_warranty(
        self, vin: str, data: WarrantyRecordCreate, current_user: User
    ) -> WarrantyRecord:
        """Create a new warranty record."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            record_dict = data.model_dump()
            record_dict["vin"] = vin

            record = WarrantyRecordModel(**record_dict)
            self.db.add(record)
            await self.db.commit()
            await self.db.refresh(record)

            logger.info(
                "Created warranty record %s for %s",
                record.id,
                sanitize_for_log(vin),
            )

            return WarrantyRecord.model_validate(record)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation creating warranty for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Duplicate or invalid warranty record")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error creating warranty for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def update_warranty(
        self,
        vin: str,
        warranty_id: int,
        data: WarrantyRecordUpdate,
        current_user: User,
    ) -> WarrantyRecord:
        """Update an existing warranty record."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(WarrantyRecordModel).where(
                    WarrantyRecordModel.vin == vin, WarrantyRecordModel.id == warranty_id
                )
            )
            record = result.scalar_one_or_none()

            if not record:
                raise HTTPException(
                    status_code=404, detail=f"Warranty record {warranty_id} not found"
                )

            update_data = data.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                setattr(record, field, value)

            await self.db.commit()
            await self.db.refresh(record)

            logger.info(
                "Updated warranty record %s for %s",
                warranty_id,
                sanitize_for_log(vin),
            )

            return WarrantyRecord.model_validate(record)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation updating warranty %s for %s: %s",
                warranty_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Database constraint violation")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error updating warranty %s for %s: %s",
                warranty_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def delete_warranty(self, vin: str, warranty_id: int, current_user: User) -> None:
        """Delete a warranty record."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(WarrantyRecordModel).where(
                    WarrantyRecordModel.vin == vin, WarrantyRecordModel.id == warranty_id
                )
            )
            record = result.scalar_one_or_none()

            if not record:
                raise HTTPException(
                    status_code=404, detail=f"Warranty record {warranty_id} not found"
                )

            await self.db.execute(
                delete(WarrantyRecordModel).where(
                    WarrantyRecordModel.vin == vin, WarrantyRecordModel.id == warranty_id
                )
            )
            await self.db.commit()

            logger.info(
                "Deleted warranty record %s for %s",
                warranty_id,
                sanitize_for_log(vin),
            )

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation deleting warranty %s for %s: %s",
                warranty_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Cannot delete record with dependent data")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error deleting warranty %s for %s: %s",
                warranty_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

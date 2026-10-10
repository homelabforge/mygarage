"""Financing record business logic service layer."""

import logging

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.financing import FinancingRecord
from app.models.user import User
from app.schemas.financing import (
    FinancingRecordCreate,
    FinancingRecordListResponse,
    FinancingRecordResponse,
    FinancingRecordUpdate,
)
from app.utils.cache import invalidate_cache_for_vehicle
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


class FinancingService:
    """Service for managing financing record business logic."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_records(
        self,
        vin: str,
        current_user: User | None,
    ) -> FinancingRecordListResponse:
        """Get all financing records for a vehicle."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)

            result = await self.db.execute(
                select(FinancingRecord)
                .where(FinancingRecord.vin == vin)
                .options(selectinload(FinancingRecord.vendor))
                .order_by(FinancingRecord.date.desc())
            )
            records = result.scalars().all()

            return FinancingRecordListResponse(
                financing_records=[FinancingRecordResponse.model_validate(r) for r in records],
                total=len(records),
            )

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error listing financing records for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def get_record(
        self,
        vin: str,
        record_id: int,
        current_user: User | None,
    ) -> FinancingRecordResponse:
        """Get a specific financing record by ID."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)

            result = await self.db.execute(
                select(FinancingRecord)
                .where(FinancingRecord.id == record_id, FinancingRecord.vin == vin)
                .options(selectinload(FinancingRecord.vendor))
            )
            record = result.scalar_one_or_none()
            if not record:
                raise HTTPException(status_code=404, detail="Financing record not found")

            return FinancingRecordResponse.model_validate(record)

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error getting financing record %s for %s: %s",
                sanitize_for_log(record_id),
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def create_record(
        self,
        vin: str,
        data: FinancingRecordCreate,
        current_user: User | None,
    ) -> FinancingRecordResponse:
        """Create a new financing record for a vehicle."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            if data.vin != vin:
                raise HTTPException(status_code=400, detail="VIN in URL and body must match")

            db_record = FinancingRecord(
                vin=vin,
                vendor_id=data.vendor_id,
                date=data.date,
                amount=data.amount,
                category=data.category,
                notes=data.notes,
            )
            self.db.add(db_record)
            await self.db.commit()
            await self.db.refresh(db_record)
            await self.db.refresh(db_record, attribute_names=["vendor"])

            logger.info(
                "Created financing record %s for %s",
                db_record.id,
                sanitize_for_log(vin),
            )

            await invalidate_cache_for_vehicle(vin)

            return FinancingRecordResponse.model_validate(db_record)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation creating financing record for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Duplicate or invalid financing record")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error creating financing record for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def update_record(
        self,
        vin: str,
        record_id: int,
        data: FinancingRecordUpdate,
        current_user: User | None,
    ) -> FinancingRecordResponse:
        """Update an existing financing record."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(FinancingRecord).where(
                    FinancingRecord.id == record_id, FinancingRecord.vin == vin
                )
            )
            record = result.scalar_one_or_none()
            if not record:
                raise HTTPException(status_code=404, detail="Financing record not found")

            update_data = data.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                setattr(record, field, value)

            await self.db.commit()
            await self.db.refresh(record)
            await self.db.refresh(record, attribute_names=["vendor"])

            logger.info(
                "Updated financing record %s for %s",
                sanitize_for_log(record_id),
                sanitize_for_log(vin),
            )

            await invalidate_cache_for_vehicle(vin)

            return FinancingRecordResponse.model_validate(record)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation updating financing record %s for %s: %s",
                sanitize_for_log(record_id),
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Database constraint violation")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error updating financing record %s for %s: %s",
                sanitize_for_log(record_id),
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def delete_record(
        self,
        vin: str,
        record_id: int,
        current_user: User | None,
    ) -> None:
        """Delete a financing record."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(FinancingRecord).where(
                    FinancingRecord.id == record_id, FinancingRecord.vin == vin
                )
            )
            record = result.scalar_one_or_none()
            if not record:
                raise HTTPException(status_code=404, detail="Financing record not found")

            await self.db.execute(
                delete(FinancingRecord).where(
                    FinancingRecord.id == record_id, FinancingRecord.vin == vin
                )
            )
            await self.db.commit()

            logger.info(
                "Deleted financing record %s for %s",
                sanitize_for_log(record_id),
                sanitize_for_log(vin),
            )

            await invalidate_cache_for_vehicle(vin)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation deleting financing record %s for %s: %s",
                sanitize_for_log(record_id),
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Cannot delete financing record")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error deleting financing record %s for %s: %s",
                sanitize_for_log(record_id),
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

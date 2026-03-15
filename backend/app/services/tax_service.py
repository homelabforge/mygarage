"""Tax/registration record business logic service layer."""

import logging

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TaxRecord
from app.models.user import User
from app.schemas.tax import (
    TaxRecordCreate,
    TaxRecordListResponse,
    TaxRecordResponse,
    TaxRecordUpdate,
)
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


class TaxRecordService:
    """Service for managing tax/registration record business logic."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_records(
        self,
        vin: str,
        current_user: User,
    ) -> TaxRecordListResponse:
        """Get all tax/registration records for a vehicle.

        Returns:
            TaxRecordListResponse with records and total count.
        """
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)

            result = await self.db.execute(
                select(TaxRecord).where(TaxRecord.vin == vin).order_by(TaxRecord.date.desc())
            )
            records = result.scalars().all()

            count_result = await self.db.execute(
                select(func.count()).select_from(TaxRecord).where(TaxRecord.vin == vin)
            )
            total = count_result.scalar() or 0

            return TaxRecordListResponse(
                records=[TaxRecordResponse.model_validate(r) for r in records],
                total=total,
            )

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error listing tax records for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def get_record(
        self,
        vin: str,
        record_id: int,
        current_user: User,
    ) -> TaxRecordResponse:
        """Get a specific tax/registration record by ID."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db)

            result = await self.db.execute(
                select(TaxRecord).where(TaxRecord.id == record_id, TaxRecord.vin == vin)
            )
            record = result.scalar_one_or_none()
            if not record:
                raise HTTPException(status_code=404, detail="Tax record not found")

            return TaxRecordResponse.model_validate(record)

        except HTTPException:
            raise
        except OperationalError as e:
            logger.error(
                "Database connection error getting tax record %s for %s: %s",
                record_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def create_record(
        self,
        vin: str,
        data: TaxRecordCreate,
        current_user: User,
    ) -> TaxRecordResponse:
        """Create a new tax/registration record."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            if data.vin != vin:
                raise HTTPException(status_code=400, detail="VIN in URL and body must match")

            record = TaxRecord(
                vin=vin,
                date=data.date,
                tax_type=data.tax_type,
                amount=data.amount,
                renewal_date=data.renewal_date,
                notes=data.notes,
            )

            self.db.add(record)
            await self.db.commit()
            await self.db.refresh(record)

            logger.info(
                "Created tax record %s for %s",
                record.id,
                sanitize_for_log(vin),
            )

            return TaxRecordResponse.model_validate(record)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation creating tax record for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Duplicate or invalid tax record")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error creating tax record for %s: %s",
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def update_record(
        self,
        vin: str,
        record_id: int,
        data: TaxRecordUpdate,
        current_user: User,
    ) -> TaxRecordResponse:
        """Update an existing tax/registration record."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(TaxRecord).where(TaxRecord.id == record_id, TaxRecord.vin == vin)
            )
            record = result.scalar_one_or_none()
            if not record:
                raise HTTPException(status_code=404, detail="Tax record not found")

            update_data = data.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                setattr(record, field, value)

            await self.db.commit()
            await self.db.refresh(record)

            logger.info(
                "Updated tax record %s for %s",
                record_id,
                sanitize_for_log(vin),
            )

            return TaxRecordResponse.model_validate(record)

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation updating tax record %s for %s: %s",
                record_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Database constraint violation")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error updating tax record %s for %s: %s",
                record_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

    async def delete_record(
        self,
        vin: str,
        record_id: int,
        current_user: User,
    ) -> None:
        """Delete a tax/registration record."""
        from app.services.auth import get_vehicle_or_403

        vin = vin.upper().strip()

        try:
            await get_vehicle_or_403(vin, current_user, self.db, require_write=True)

            result = await self.db.execute(
                select(TaxRecord).where(TaxRecord.id == record_id, TaxRecord.vin == vin)
            )
            record = result.scalar_one_or_none()
            if not record:
                raise HTTPException(status_code=404, detail="Tax record not found")

            await self.db.execute(
                delete(TaxRecord).where(TaxRecord.id == record_id, TaxRecord.vin == vin)
            )
            await self.db.commit()

            logger.info(
                "Deleted tax record %s for %s",
                record_id,
                sanitize_for_log(vin),
            )

        except HTTPException:
            raise
        except IntegrityError as e:
            await self.db.rollback()
            logger.error(
                "Database constraint violation deleting tax record %s for %s: %s",
                record_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=409, detail="Cannot delete record with dependent data")
        except OperationalError as e:
            await self.db.rollback()
            logger.error(
                "Database connection error deleting tax record %s for %s: %s",
                record_id,
                sanitize_for_log(vin),
                sanitize_for_log(e),
            )
            raise HTTPException(status_code=503, detail="Database temporarily unavailable")

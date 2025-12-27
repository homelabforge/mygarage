"""Odometer Record CRUD API endpoints."""

import logging
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from sqlalchemy.exc import IntegrityError, OperationalError
from typing import Optional

from app.database import get_db
from app.models.odometer import OdometerRecord
from app.models.vehicle import Vehicle
from app.models.user import User
from app.schemas.odometer import (
    OdometerRecordCreate,
    OdometerRecordUpdate,
    OdometerRecordResponse,
    OdometerRecordListResponse,
)
from app.services.auth import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vehicles/{vin}/odometer", tags=["Odometer Records"])


@router.get("", response_model=OdometerRecordListResponse)
async def list_odometer_records(
    vin: str,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """
    Get all odometer records for a vehicle.

    **Path Parameters:**
    - **vin**: Vehicle VIN

    **Query Parameters:**
    - **skip**: Number of records to skip (pagination)
    - **limit**: Maximum number of records to return

    **Returns:**
    - List of odometer records with total count and latest mileage
    """
    vin = vin.upper().strip()

    try:
        # Verify vehicle exists
        result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
        vehicle = result.scalar_one_or_none()

        if not vehicle:
            raise HTTPException(
                status_code=404, detail=f"Vehicle with VIN {vin} not found"
            )

        # Get odometer records
        result = await db.execute(
            select(OdometerRecord)
            .where(OdometerRecord.vin == vin)
            .order_by(OdometerRecord.date.desc())
            .offset(skip)
            .limit(limit)
        )
        records = result.scalars().all()

        # Get total count
        count_result = await db.execute(
            select(func.count())
            .select_from(OdometerRecord)
            .where(OdometerRecord.vin == vin)
        )
        total = count_result.scalar()

        # Get latest mileage
        latest_result = await db.execute(
            select(OdometerRecord.mileage)
            .where(OdometerRecord.vin == vin)
            .order_by(OdometerRecord.date.desc())
            .limit(1)
        )
        latest_mileage = latest_result.scalar_one_or_none()

        return OdometerRecordListResponse(
            records=[OdometerRecordResponse.model_validate(r) for r in records],
            total=total,
            latest_mileage=latest_mileage,
        )

    except HTTPException:
        raise
    except OperationalError as e:
        logger.error(
            "Database connection error listing odometer records for %s: %s", vin, str(e)
        )
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")


@router.get("/{record_id}", response_model=OdometerRecordResponse)
async def get_odometer_record(
    vin: str,
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """
    Get a specific odometer record.

    **Path Parameters:**
    - **vin**: Vehicle VIN
    - **record_id**: Odometer record ID

    **Returns:**
    - Odometer record details

    **Raises:**
    - **404**: Record not found
    """
    vin = vin.upper().strip()

    result = await db.execute(
        select(OdometerRecord)
        .where(OdometerRecord.id == record_id)
        .where(OdometerRecord.vin == vin)
    )
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(
            status_code=404, detail=f"Odometer record {record_id} not found"
        )

    return OdometerRecordResponse.model_validate(record)


@router.post("", response_model=OdometerRecordResponse, status_code=201)
async def create_odometer_record(
    vin: str,
    record_data: OdometerRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """
    Create a new odometer record.

    **Path Parameters:**
    - **vin**: Vehicle VIN

    **Request Body:**
    - Odometer record data

    **Returns:**
    - Created odometer record

    **Raises:**
    - **404**: Vehicle not found
    - **500**: Database error
    """
    vin = vin.upper().strip()

    try:
        # Verify vehicle exists
        result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
        vehicle = result.scalar_one_or_none()

        if not vehicle:
            raise HTTPException(
                status_code=404, detail=f"Vehicle with VIN {vin} not found"
            )

        # Create odometer record
        record_dict = record_data.model_dump()
        record_dict["vin"] = vin
        record = OdometerRecord(**record_dict)

        db.add(record)
        await db.commit()
        await db.refresh(record)

        logger.info("Created odometer record %s for %s", record.id, vin)

        return OdometerRecordResponse.model_validate(record)

    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(
            "Database constraint violation creating odometer record for %s: %s",
            vin,
            str(e),
        )
        raise HTTPException(
            status_code=409, detail="Duplicate or invalid odometer record"
        )
    except OperationalError as e:
        await db.rollback()
        logger.error(
            "Database connection error creating odometer record for %s: %s", vin, str(e)
        )
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")


@router.put("/{record_id}", response_model=OdometerRecordResponse)
async def update_odometer_record(
    vin: str,
    record_id: int,
    record_data: OdometerRecordUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """
    Update an existing odometer record.

    **Path Parameters:**
    - **vin**: Vehicle VIN
    - **record_id**: Odometer record ID

    **Request Body:**
    - Updated odometer record data

    **Returns:**
    - Updated odometer record

    **Raises:**
    - **404**: Record not found
    - **500**: Database error
    """
    vin = vin.upper().strip()

    try:
        # Get existing record
        result = await db.execute(
            select(OdometerRecord)
            .where(OdometerRecord.id == record_id)
            .where(OdometerRecord.vin == vin)
        )
        record = result.scalar_one_or_none()

        if not record:
            raise HTTPException(
                status_code=404, detail=f"Odometer record {record_id} not found"
            )

        # Update fields
        update_data = record_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(record, field, value)

        await db.commit()
        await db.refresh(record)

        logger.info("Updated odometer record %s for %s", record_id, vin)

        return OdometerRecordResponse.model_validate(record)

    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(
            "Database constraint violation updating odometer record %s for %s: %s",
            record_id,
            vin,
            str(e),
        )
        raise HTTPException(status_code=409, detail="Database constraint violation")
    except OperationalError as e:
        await db.rollback()
        logger.error(
            "Database connection error updating odometer record %s for %s: %s",
            record_id,
            vin,
            str(e),
        )
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")


@router.delete("/{record_id}", status_code=204)
async def delete_odometer_record(
    vin: str,
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """
    Delete an odometer record.

    **Path Parameters:**
    - **vin**: Vehicle VIN
    - **record_id**: Odometer record ID

    **Raises:**
    - **404**: Record not found
    - **500**: Database error
    """
    vin = vin.upper().strip()

    try:
        # Check if record exists
        result = await db.execute(
            select(OdometerRecord)
            .where(OdometerRecord.id == record_id)
            .where(OdometerRecord.vin == vin)
        )
        record = result.scalar_one_or_none()

        if not record:
            raise HTTPException(
                status_code=404, detail=f"Odometer record {record_id} not found"
            )

        # Delete record
        await db.execute(
            delete(OdometerRecord)
            .where(OdometerRecord.id == record_id)
            .where(OdometerRecord.vin == vin)
        )
        await db.commit()

        logger.info("Deleted odometer record %s for %s", record_id, vin)

        return None

    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(
            "Database constraint violation deleting odometer record %s for %s: %s",
            record_id,
            vin,
            str(e),
        )
        raise HTTPException(
            status_code=409, detail="Cannot delete record with dependent data"
        )
    except OperationalError as e:
        await db.rollback()
        logger.error(
            "Database connection error deleting odometer record %s for %s: %s",
            record_id,
            vin,
            str(e),
        )
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")

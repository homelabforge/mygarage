"""Hours Record CRUD API endpoints."""

import logging
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.hours import HoursRecord
from app.models.user import User
from app.schemas.hours import (
    HoursRecordCreate,
    HoursRecordListResponse,
    HoursRecordResponse,
    HoursRecordUpdate,
    NearestHoursResponse,
)
from app.services.auth import get_vehicle_or_403, require_auth
from app.services.hours_service import latest_engine_hours_and_date, nearest_hours_record
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vehicles/{vin}/hours", tags=["Hours Records"])


@router.get("", response_model=HoursRecordListResponse)
async def list_hours_records(
    vin: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """
    Get all hours records for a vehicle.

    **Path Parameters:**
    - **vin**: Vehicle VIN

    **Query Parameters:**
    - **skip**: Number of records to skip (pagination)
    - **limit**: Maximum number of records to return

    **Returns:**
    - List of hours records with total count and the canonical latest reading
    """
    vin = vin.upper().strip()

    try:
        await get_vehicle_or_403(vin, current_user, db)

        # Get hours records
        result = await db.execute(
            select(HoursRecord)
            .where(HoursRecord.vin == vin)
            .order_by(HoursRecord.date.desc())
            .offset(skip)
            .limit(limit)
        )
        records = result.scalars().all()

        # Get total count
        count_result = await db.execute(
            select(func.count()).select_from(HoursRecord).where(HoursRecord.vin == vin)
        )
        total = count_result.scalar()

        # Canonical latest reading -- the ONE shared helper, never re-derived.
        latest_engine_hours, _latest_date = await latest_engine_hours_and_date(db, vin)

        return HoursRecordListResponse(
            records=[HoursRecordResponse.model_validate(r) for r in records],
            total=total,
            latest_engine_hours=latest_engine_hours,
        )

    except HTTPException:
        raise
    except OperationalError as e:
        logger.error(
            "Database connection error listing hours records for %s: %s",
            sanitize_for_log(vin),
            sanitize_for_log(str(e)),
        )
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")


# Above `/{record_id}`, or FastAPI reads "nearest" as a record id and answers 422.
@router.get("/nearest", response_model=NearestHoursResponse)
async def nearest_hours_reading(
    vin: str,
    on: date_type = Query(..., alias="date"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> NearestHoursResponse:
    """The hours reading closest to a date, for prefilling a tire dialog. 404 when there are none."""
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db)
    record = await nearest_hours_record(db, vin, on)
    if record is None:
        raise HTTPException(status_code=404, detail="No engine hours readings for this vehicle")
    return NearestHoursResponse(
        date=record.date,
        engine_hours=record.engine_hours,
        source=record.source,
        days_away=(record.date - on).days,
    )


@router.get("/{record_id}", response_model=HoursRecordResponse)
async def get_hours_record(
    vin: str,
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """
    Get a specific hours record.

    **Path Parameters:**
    - **vin**: Vehicle VIN
    - **record_id**: Hours record ID

    **Returns:**
    - Hours record details

    **Raises:**
    - **404**: Record not found
    """
    vin = vin.upper().strip()

    await get_vehicle_or_403(vin, current_user, db)

    result = await db.execute(
        select(HoursRecord).where(HoursRecord.id == record_id).where(HoursRecord.vin == vin)
    )
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(status_code=404, detail=f"Hours record {record_id} not found")

    return HoursRecordResponse.model_validate(record)


@router.post("", response_model=HoursRecordResponse, status_code=201)
async def create_hours_record(
    vin: str,
    record_data: HoursRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """
    Create a new hours record.

    A manually-entered reading -- ``source`` defaults to ``'manual'`` with both
    ``fuel_record_id`` and ``service_visit_id`` left null (the model column
    default), matching how synced rows are distinguished from manual ones.

    **Path Parameters:**
    - **vin**: Vehicle VIN

    **Request Body:**
    - Hours record data

    **Returns:**
    - Created hours record

    **Raises:**
    - **404**: Vehicle not found
    - **500**: Database error
    """
    vin = vin.upper().strip()

    try:
        await get_vehicle_or_403(vin, current_user, db, require_write=True)

        # Create hours record
        record_dict = record_data.model_dump()
        record_dict["vin"] = vin
        record = HoursRecord(**record_dict)

        db.add(record)
        await db.commit()
        await db.refresh(record)

        logger.info("Created hours record %s for %s", record.id, sanitize_for_log(vin))

        return HoursRecordResponse.model_validate(record)

    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(
            "Database constraint violation creating hours record for %s: %s",
            sanitize_for_log(vin),
            sanitize_for_log(str(e)),
        )
        raise HTTPException(status_code=409, detail="Duplicate or invalid hours record")
    except OperationalError as e:
        await db.rollback()
        logger.error(
            "Database connection error creating hours record for %s: %s",
            sanitize_for_log(vin),
            sanitize_for_log(str(e)),
        )
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")


@router.put("/{record_id}", response_model=HoursRecordResponse)
async def update_hours_record(
    vin: str,
    record_id: int,
    record_data: HoursRecordUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """
    Update an existing hours record.

    **Path Parameters:**
    - **vin**: Vehicle VIN
    - **record_id**: Hours record ID

    **Request Body:**
    - Updated hours record data

    **Returns:**
    - Updated hours record

    **Raises:**
    - **404**: Record not found
    - **500**: Database error
    """
    vin = vin.upper().strip()

    try:
        await get_vehicle_or_403(vin, current_user, db, require_write=True)

        # Get existing record
        result = await db.execute(
            select(HoursRecord).where(HoursRecord.id == record_id).where(HoursRecord.vin == vin)
        )
        record = result.scalar_one_or_none()

        if not record:
            raise HTTPException(status_code=404, detail=f"Hours record {record_id} not found")

        # Update fields
        update_data = record_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(record, field, value)

        await db.commit()
        await db.refresh(record)

        logger.info("Updated hours record %s for %s", record_id, sanitize_for_log(vin))

        return HoursRecordResponse.model_validate(record)

    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(
            "Database constraint violation updating hours record %s for %s: %s",
            record_id,
            sanitize_for_log(vin),
            sanitize_for_log(str(e)),
        )
        raise HTTPException(status_code=409, detail="Database constraint violation")
    except OperationalError as e:
        await db.rollback()
        logger.error(
            "Database connection error updating hours record %s for %s: %s",
            record_id,
            sanitize_for_log(vin),
            sanitize_for_log(str(e)),
        )
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")


@router.delete("/{record_id}", status_code=204)
async def delete_hours_record(
    vin: str,
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """
    Delete an hours record.

    **Path Parameters:**
    - **vin**: Vehicle VIN
    - **record_id**: Hours record ID

    **Raises:**
    - **404**: Record not found
    - **500**: Database error
    """
    vin = vin.upper().strip()

    try:
        await get_vehicle_or_403(vin, current_user, db, require_write=True)

        # Check if record exists
        result = await db.execute(
            select(HoursRecord).where(HoursRecord.id == record_id).where(HoursRecord.vin == vin)
        )
        record = result.scalar_one_or_none()

        if not record:
            raise HTTPException(status_code=404, detail=f"Hours record {record_id} not found")

        # Delete record
        await db.execute(
            delete(HoursRecord).where(HoursRecord.id == record_id).where(HoursRecord.vin == vin)
        )
        await db.commit()

        logger.info("Deleted hours record %s for %s", record_id, sanitize_for_log(vin))

        return None

    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(
            "Database constraint violation deleting hours record %s for %s: %s",
            record_id,
            sanitize_for_log(vin),
            sanitize_for_log(str(e)),
        )
        raise HTTPException(status_code=409, detail="Cannot delete record with dependent data")
    except OperationalError as e:
        await db.rollback()
        logger.error(
            "Database connection error deleting hours record %s for %s: %s",
            record_id,
            sanitize_for_log(vin),
            sanitize_for_log(str(e)),
        )
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")

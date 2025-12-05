"""Fuel Record CRUD API endpoints with MPG calculation."""

import logging
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.database import get_db
from app.models.user import User
from app.schemas.fuel import (
    FuelRecordCreate,
    FuelRecordUpdate,
    FuelRecordResponse,
    FuelRecordListResponse,
)
from app.services.auth import require_auth
from app.services.fuel_service import FuelRecordService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vehicles/{vin}/fuel", tags=["Fuel Records"])


@router.get("", response_model=FuelRecordListResponse)
async def list_fuel_records(
    vin: str,
    skip: int = 0,
    limit: int = 100,
    include_hauling: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth)
):
    """
    Get all fuel records for a vehicle with MPG calculations.

    **Path Parameters:**
    - **vin**: Vehicle VIN

    **Query Parameters:**
    - **skip**: Number of records to skip (pagination)
    - **limit**: Maximum number of records to return
    - **include_hauling**: Include towing/hauling records in MPG calculation (default: False)

    **Returns:**
    - List of fuel records with MPG and average MPG

    **Security:**
    - Users can only access fuel records for their own vehicles
    - Admin users can access all fuel records
    """
    service = FuelRecordService(db)
    responses, total, avg_mpg = await service.list_fuel_records(
        vin, current_user, skip, limit, include_hauling
    )

    return FuelRecordListResponse(
        records=responses,
        total=total,
        average_mpg=avg_mpg
    )


@router.get("/{record_id}", response_model=FuelRecordResponse)
async def get_fuel_record(
    vin: str,
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth)
):
    """
    Get a specific fuel record with MPG calculation.

    **Path Parameters:**
    - **vin**: Vehicle VIN
    - **record_id**: Fuel record ID

    **Returns:**
    - Fuel record details with MPG

    **Raises:**
    - **404**: Record not found
    - **403**: Not authorized

    **Security:**
    - Users can only access fuel records for their own vehicles
    - Admin users can access all fuel records
    """
    service = FuelRecordService(db)
    record, mpg = await service.get_fuel_record(vin, record_id, current_user)

    # Build response with MPG
    record_dict = record.__dict__.copy()
    record_dict['mpg'] = mpg

    return FuelRecordResponse(**record_dict)


@router.post("", response_model=FuelRecordResponse, status_code=201)
async def create_fuel_record(
    vin: str,
    record_data: FuelRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth)
):
    """
    Create a new fuel record with MPG calculation.

    **Security:**
    - Users can only create fuel records for their own vehicles
    - Admin users can create fuel records for all vehicles
    """
    service = FuelRecordService(db)
    record, mpg = await service.create_fuel_record(vin, record_data, current_user)

    # Build response with MPG
    record_dict = record.__dict__.copy()
    record_dict['mpg'] = mpg

    return FuelRecordResponse(**record_dict)


@router.put("/{record_id}", response_model=FuelRecordResponse)
async def update_fuel_record(
    vin: str,
    record_id: int,
    record_data: FuelRecordUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth)
):
    """
    Update an existing fuel record.

    **Security:**
    - Users can only update fuel records for their own vehicles
    - Admin users can update all fuel records
    """
    service = FuelRecordService(db)
    record, mpg = await service.update_fuel_record(vin, record_id, record_data, current_user)

    # Build response with MPG
    record_dict = record.__dict__.copy()
    record_dict['mpg'] = mpg

    return FuelRecordResponse(**record_dict)


@router.delete("/{record_id}", status_code=204)
async def delete_fuel_record(
    vin: str,
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth)
):
    """
    Delete a fuel record.

    **Security:**
    - Users can only delete fuel records for their own vehicles
    - Admin users can delete all fuel records
    """
    service = FuelRecordService(db)
    await service.delete_fuel_record(vin, record_id, current_user)

    return None

"""DEF (Diesel Exhaust Fluid) Record CRUD API endpoints."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.def_record import (
    DEFAnalytics,
    DEFRecordCreate,
    DEFRecordListResponse,
    DEFRecordResponse,
    DEFRecordUpdate,
)
from app.services.auth import require_auth
from app.services.def_service import DEFRecordService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vehicles/{vin}/def", tags=["DEF Records"])


@router.get("", response_model=DEFRecordListResponse)
async def list_def_records(
    vin: str,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Get all DEF records for a vehicle.

    **Path Parameters:**
    - **vin**: Vehicle VIN

    **Query Parameters:**
    - **skip**: Number of records to skip (pagination)
    - **limit**: Maximum number of records to return
    """
    service = DEFRecordService(db)
    responses, total = await service.list_def_records(vin, current_user, skip, limit)
    return DEFRecordListResponse(records=responses, total=total)


@router.get("/analytics", response_model=DEFAnalytics)
async def get_def_analytics(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Get DEF analytics and consumption predictions.

    **Path Parameters:**
    - **vin**: Vehicle VIN

    **Returns:**
    - DEF analytics including consumption rate, estimated remaining, and predictions
    """
    service = DEFRecordService(db)
    return await service.get_def_analytics(vin, current_user)


@router.get("/{record_id}", response_model=DEFRecordResponse)
async def get_def_record(
    vin: str,
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Get a specific DEF record."""
    service = DEFRecordService(db)
    record = await service.get_def_record(vin, record_id, current_user)
    return DEFRecordResponse.model_validate(record)


@router.post("", response_model=DEFRecordResponse, status_code=201)
async def create_def_record(
    vin: str,
    record_data: DEFRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Create a new DEF record."""
    service = DEFRecordService(db)
    record = await service.create_def_record(vin, record_data, current_user)
    return DEFRecordResponse.model_validate(record)


@router.put("/{record_id}", response_model=DEFRecordResponse)
async def update_def_record(
    vin: str,
    record_id: int,
    record_data: DEFRecordUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Update an existing DEF record."""
    service = DEFRecordService(db)
    record = await service.update_def_record(vin, record_id, record_data, current_user)
    return DEFRecordResponse.model_validate(record)


@router.delete("/{record_id}", status_code=204)
async def delete_def_record(
    vin: str,
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Delete a DEF record."""
    service = DEFRecordService(db)
    await service.delete_def_record(vin, record_id, current_user)
    return None

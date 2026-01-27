"""Service Record CRUD API endpoints."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.service import (
    ServiceRecordCreate,
    ServiceRecordListResponse,
    ServiceRecordResponse,
    ServiceRecordUpdate,
)
from app.services.auth import require_auth
from app.services.service_service import ServiceRecordService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vehicles/{vin}/service", tags=["Service Records"])


@router.get("", response_model=ServiceRecordListResponse)
async def list_service_records(
    vin: str,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get all service records for a vehicle.

    **Path Parameters:**
    - **vin**: Vehicle VIN

    **Query Parameters:**
    - **skip**: Number of records to skip (pagination)
    - **limit**: Maximum number of records to return

    **Returns:**
    - List of service records with total count

    **Security:**
    - Users can only access service records for their own vehicles
    - Admin users can access all service records
    """
    service = ServiceRecordService(db)
    record_responses, total = await service.list_service_records(
        vin, current_user, skip, limit
    )

    return ServiceRecordListResponse(records=record_responses, total=total)


@router.get("/{record_id}", response_model=ServiceRecordResponse)
async def get_service_record(
    vin: str,
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get a specific service record.

    **Path Parameters:**
    - **vin**: Vehicle VIN
    - **record_id**: Service record ID

    **Returns:**
    - Service record details

    **Raises:**
    - **404**: Record not found
    - **403**: Not authorized

    **Security:**
    - Users can only access service records for their own vehicles
    - Admin users can access all service records
    """
    service = ServiceRecordService(db)
    record = await service.get_service_record(vin, record_id, current_user)

    return ServiceRecordResponse.model_validate(record)


@router.post("", response_model=ServiceRecordResponse, status_code=201)
async def create_service_record(
    vin: str,
    record_data: ServiceRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Create a new service record.

    **Path Parameters:**
    - **vin**: Vehicle VIN

    **Request Body:**
    - Service record data

    **Returns:**
    - Created service record

    **Raises:**
    - **404**: Vehicle not found
    - **403**: Not authorized
    - **500**: Database error

    **Security:**
    - Users can only create service records for their own vehicles
    - Admin users can create service records for all vehicles
    """
    service = ServiceRecordService(db)
    record = await service.create_service_record(vin, record_data, current_user)

    return ServiceRecordResponse.model_validate(record)


@router.put("/{record_id}", response_model=ServiceRecordResponse)
async def update_service_record(
    vin: str,
    record_id: int,
    record_data: ServiceRecordUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Update an existing service record.

    **Path Parameters:**
    - **vin**: Vehicle VIN
    - **record_id**: Service record ID

    **Request Body:**
    - Updated service record data

    **Returns:**
    - Updated service record

    **Raises:**
    - **404**: Record not found
    - **403**: Not authorized
    - **500**: Database error

    **Security:**
    - Users can only update service records for their own vehicles
    - Admin users can update all service records
    """
    service = ServiceRecordService(db)
    record = await service.update_service_record(
        vin, record_id, record_data, current_user
    )

    return ServiceRecordResponse.model_validate(record)


@router.delete("/{record_id}", status_code=204)
async def delete_service_record(
    vin: str,
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Delete a service record.

    **Path Parameters:**
    - **vin**: Vehicle VIN
    - **record_id**: Service record ID

    **Raises:**
    - **404**: Record not found
    - **403**: Not authorized
    - **500**: Database error

    **Security:**
    - Users can only delete service records for their own vehicles
    - Admin users can delete all service records
    """
    service = ServiceRecordService(db)
    await service.delete_service_record(vin, record_id, current_user)

    return None

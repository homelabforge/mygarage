"""Maintenance Schedule API endpoints."""

import logging
from typing import Optional
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.maintenance_schedule import (
    MaintenanceScheduleItemCreate,
    MaintenanceScheduleItemUpdate,
    MaintenanceScheduleItemResponse,
    MaintenanceScheduleListResponse,
    ApplyTemplateRequest,
    ApplyTemplateResponse,
)
from app.services.auth import require_auth
from app.services.maintenance_schedule_service import MaintenanceScheduleService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/vehicles/{vin}/maintenance-schedule", tags=["Maintenance Schedule"]
)


@router.get("", response_model=MaintenanceScheduleListResponse)
async def list_schedule_items(
    vin: str,
    status: Optional[str] = Query(
        None,
        description="Filter by status (never_performed, overdue, due_soon, on_track)",
    ),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=500, description="Maximum records to return"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get maintenance schedule for a vehicle with status.

    **Path Parameters:**
    - **vin**: Vehicle VIN

    **Query Parameters:**
    - **status**: Optional filter by status
    - **skip**: Number of records to skip (pagination)
    - **limit**: Maximum number of records to return

    **Returns:**
    - List of schedule items with status and counts

    **Security:**
    - Users can only access schedules for their own vehicles
    - Admin users can access all schedules
    """
    service = MaintenanceScheduleService(db)
    return await service.list_schedule_items(vin, current_user, skip, limit, status)


@router.get("/{item_id}", response_model=MaintenanceScheduleItemResponse)
async def get_schedule_item(
    vin: str,
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get a specific schedule item.

    **Path Parameters:**
    - **vin**: Vehicle VIN
    - **item_id**: Schedule item ID

    **Returns:**
    - Schedule item details with status

    **Raises:**
    - **404**: Item not found
    - **403**: Not authorized
    """
    service = MaintenanceScheduleService(db)
    item = await service.get_schedule_item(vin, item_id, current_user)

    # Calculate status
    current_date = date.today()
    from app.models.odometer import OdometerRecord
    from sqlalchemy import select

    result = await db.execute(
        select(OdometerRecord.mileage)
        .where(OdometerRecord.vin == vin.upper().strip())
        .order_by(OdometerRecord.date.desc())
        .limit(1)
    )
    row = result.first()
    current_mileage = row[0] if row else None

    status = item.calculate_status(current_date, current_mileage)
    next_due_date = item.next_due_date
    next_due_mileage = item.next_due_mileage

    days_until = (next_due_date - current_date).days if next_due_date else None
    miles_until = (
        (next_due_mileage - current_mileage)
        if next_due_mileage and current_mileage
        else None
    )

    return MaintenanceScheduleItemResponse(
        id=item.id,
        vin=item.vin,
        name=item.name,
        component_category=item.component_category,
        item_type=item.item_type,
        interval_months=item.interval_months,
        interval_miles=item.interval_miles,
        source=item.source,
        template_item_id=item.template_item_id,
        last_performed_date=item.last_performed_date,
        last_performed_mileage=item.last_performed_mileage,
        last_service_line_item_id=item.last_service_line_item_id,
        next_due_date=next_due_date,
        next_due_mileage=next_due_mileage,
        status=status,
        days_until_due=days_until,
        miles_until_due=miles_until,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.post("", response_model=MaintenanceScheduleItemResponse, status_code=201)
async def create_schedule_item(
    vin: str,
    item_data: MaintenanceScheduleItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Create a new maintenance schedule item.

    **Path Parameters:**
    - **vin**: Vehicle VIN

    **Request Body:**
    - Schedule item data

    **Returns:**
    - Created schedule item

    **Raises:**
    - **404**: Vehicle not found
    - **403**: Not authorized
    """
    service = MaintenanceScheduleService(db)
    item = await service.create_schedule_item(vin, item_data, current_user)

    return MaintenanceScheduleItemResponse(
        id=item.id,
        vin=item.vin,
        name=item.name,
        component_category=item.component_category,
        item_type=item.item_type,
        interval_months=item.interval_months,
        interval_miles=item.interval_miles,
        source=item.source,
        template_item_id=item.template_item_id,
        last_performed_date=item.last_performed_date,
        last_performed_mileage=item.last_performed_mileage,
        last_service_line_item_id=item.last_service_line_item_id,
        next_due_date=item.next_due_date,
        next_due_mileage=item.next_due_mileage,
        status="never_performed",
        days_until_due=None,
        miles_until_due=None,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.put("/{item_id}", response_model=MaintenanceScheduleItemResponse)
async def update_schedule_item(
    vin: str,
    item_id: int,
    item_data: MaintenanceScheduleItemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Update an existing schedule item.

    **Path Parameters:**
    - **vin**: Vehicle VIN
    - **item_id**: Schedule item ID

    **Request Body:**
    - Schedule item update data

    **Returns:**
    - Updated schedule item

    **Raises:**
    - **404**: Item not found
    - **403**: Not authorized
    """
    service = MaintenanceScheduleService(db)
    item = await service.update_schedule_item(vin, item_id, item_data, current_user)

    # Calculate status
    current_date = date.today()
    status = item.calculate_status(current_date, None)

    return MaintenanceScheduleItemResponse(
        id=item.id,
        vin=item.vin,
        name=item.name,
        component_category=item.component_category,
        item_type=item.item_type,
        interval_months=item.interval_months,
        interval_miles=item.interval_miles,
        source=item.source,
        template_item_id=item.template_item_id,
        last_performed_date=item.last_performed_date,
        last_performed_mileage=item.last_performed_mileage,
        last_service_line_item_id=item.last_service_line_item_id,
        next_due_date=item.next_due_date,
        next_due_mileage=item.next_due_mileage,
        status=status,
        days_until_due=None,
        miles_until_due=None,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.delete("/{item_id}", status_code=204)
async def delete_schedule_item(
    vin: str,
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Delete a schedule item.

    **Path Parameters:**
    - **vin**: Vehicle VIN
    - **item_id**: Schedule item ID

    **Raises:**
    - **404**: Item not found
    - **403**: Not authorized
    """
    service = MaintenanceScheduleService(db)
    await service.delete_schedule_item(vin, item_id, current_user)
    return None


@router.post("/apply-template", response_model=ApplyTemplateResponse)
async def apply_template(
    vin: str,
    request: ApplyTemplateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Apply a maintenance template to a vehicle.

    **Path Parameters:**
    - **vin**: Vehicle VIN

    **Request Body:**
    - Template source and optional initial date/mileage

    **Returns:**
    - Count of items created/skipped

    **Raises:**
    - **404**: Vehicle or template not found
    - **403**: Not authorized
    """
    service = MaintenanceScheduleService(db)
    return await service.apply_template(vin, request, current_user)

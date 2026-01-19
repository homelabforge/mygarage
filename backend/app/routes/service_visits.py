"""Service Visit CRUD API endpoints."""

import logging
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.service_visit import (
    ServiceVisitCreate,
    ServiceVisitUpdate,
    ServiceVisitResponse,
    ServiceVisitListResponse,
    ServiceLineItemCreate,
    ServiceLineItemResponse,
)
from app.services.auth import require_auth
from app.services.service_visit_service import ServiceVisitService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vehicles/{vin}/service-visits", tags=["Service Visits"])


@router.get("", response_model=ServiceVisitListResponse)
async def list_service_visits(
    vin: str,
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=500, description="Maximum records to return"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get all service visits for a vehicle.

    **Path Parameters:**
    - **vin**: Vehicle VIN

    **Query Parameters:**
    - **skip**: Number of records to skip (pagination)
    - **limit**: Maximum number of records to return

    **Returns:**
    - List of service visits with total count

    **Security:**
    - Users can only access service visits for their own vehicles
    - Admin users can access all service visits
    """
    service = ServiceVisitService(db)
    visits, total = await service.list_service_visits(vin, current_user, skip, limit)
    return ServiceVisitListResponse(visits=visits, total=total)


@router.get("/{visit_id}", response_model=ServiceVisitResponse)
async def get_service_visit(
    vin: str,
    visit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get a specific service visit.

    **Path Parameters:**
    - **vin**: Vehicle VIN
    - **visit_id**: Service visit ID

    **Returns:**
    - Service visit details with line items

    **Raises:**
    - **404**: Visit not found
    - **403**: Not authorized
    """
    service = ServiceVisitService(db)
    visit = await service.get_service_visit(vin, visit_id, current_user)
    return service._visit_to_response(visit)


@router.post("", response_model=ServiceVisitResponse, status_code=201)
async def create_service_visit(
    vin: str,
    visit_data: ServiceVisitCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Create a new service visit with line items.

    **Path Parameters:**
    - **vin**: Vehicle VIN

    **Request Body:**
    - Service visit data including line items

    **Returns:**
    - Created service visit

    **Raises:**
    - **404**: Vehicle not found
    - **403**: Not authorized
    - **409**: Invalid data
    """
    service = ServiceVisitService(db)
    visit = await service.create_service_visit(vin, visit_data, current_user)
    return service._visit_to_response(visit)


@router.put("/{visit_id}", response_model=ServiceVisitResponse)
async def update_service_visit(
    vin: str,
    visit_id: int,
    visit_data: ServiceVisitUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Update an existing service visit.

    **Path Parameters:**
    - **vin**: Vehicle VIN
    - **visit_id**: Service visit ID

    **Request Body:**
    - Service visit update data

    **Returns:**
    - Updated service visit

    **Raises:**
    - **404**: Visit not found
    - **403**: Not authorized
    """
    service = ServiceVisitService(db)
    visit = await service.update_service_visit(vin, visit_id, visit_data, current_user)
    return service._visit_to_response(visit)


@router.delete("/{visit_id}", status_code=204)
async def delete_service_visit(
    vin: str,
    visit_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Delete a service visit.

    **Path Parameters:**
    - **vin**: Vehicle VIN
    - **visit_id**: Service visit ID

    **Raises:**
    - **404**: Visit not found
    - **403**: Not authorized
    """
    service = ServiceVisitService(db)
    await service.delete_service_visit(vin, visit_id, current_user)
    return None


@router.post(
    "/{visit_id}/line-items", response_model=ServiceLineItemResponse, status_code=201
)
async def add_line_item(
    vin: str,
    visit_id: int,
    item_data: ServiceLineItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Add a line item to an existing service visit.

    **Path Parameters:**
    - **vin**: Vehicle VIN
    - **visit_id**: Service visit ID

    **Request Body:**
    - Line item data

    **Returns:**
    - Created line item

    **Raises:**
    - **404**: Visit not found
    - **403**: Not authorized
    """
    service = ServiceVisitService(db)
    line_item = await service.add_line_item(vin, visit_id, item_data, current_user)
    return ServiceLineItemResponse(
        id=line_item.id,
        visit_id=line_item.visit_id,
        description=line_item.description,
        cost=line_item.cost,
        notes=line_item.notes,
        is_inspection=line_item.is_inspection,
        inspection_result=line_item.inspection_result,
        inspection_severity=line_item.inspection_severity,
        schedule_item_id=line_item.schedule_item_id,
        triggered_by_inspection_id=line_item.triggered_by_inspection_id,
        created_at=line_item.created_at,
        is_failed_inspection=line_item.is_failed_inspection,
        needs_followup=line_item.needs_followup,
    )


@router.delete("/{visit_id}/line-items/{line_item_id}", status_code=204)
async def delete_line_item(
    vin: str,
    visit_id: int,
    line_item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Delete a line item from a service visit.

    **Path Parameters:**
    - **vin**: Vehicle VIN
    - **visit_id**: Service visit ID
    - **line_item_id**: Line item ID

    **Raises:**
    - **404**: Line item not found
    - **403**: Not authorized
    """
    service = ServiceVisitService(db)
    await service.delete_line_item(vin, visit_id, line_item_id, current_user)
    return None

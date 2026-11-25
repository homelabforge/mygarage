"""Service Visit CRUD API endpoints."""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.schemas.service_visit import (
    ServiceInvoiceReadResponse,
    ServiceLineItemCreate,
    ServiceLineItemResponse,
    ServiceVisitCreate,
    ServiceVisitListResponse,
    ServiceVisitResponse,
    ServiceVisitUpdate,
)
from app.services.auth import get_vehicle_or_403, require_auth
from app.services.service_invoice_service import read_service_invoice
from app.services.service_visit_service import ServiceVisitService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vehicles/{vin}/service-visits", tags=["Service Visits"])
limiter = Limiter(key_func=get_remote_address)

MAX_INVOICE_UPLOAD_BYTES = settings.max_upload_size_bytes


@router.get("", response_model=ServiceVisitListResponse)
async def list_service_visits(
    vin: str,
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=500, description="Maximum records to return"),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
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
    current_user: User | None = Depends(require_auth),
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
    current_user: User | None = Depends(require_auth),
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
    current_user: User | None = Depends(require_auth),
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
    current_user: User | None = Depends(require_auth),
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


@router.post("/{visit_id}/line-items", response_model=ServiceLineItemResponse, status_code=201)
async def add_line_item(
    vin: str,
    visit_id: int,
    item_data: ServiceLineItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
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
    return service._line_item_to_response(line_item)


@router.delete("/{visit_id}/line-items/{line_item_id}", status_code=204)
async def delete_line_item(
    vin: str,
    visit_id: int,
    line_item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
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


@router.post("/read-invoice", response_model=ServiceInvoiceReadResponse)
@limiter.limit(settings.rate_limit_uploads)
async def read_invoice(
    request: Request,
    vin: str,
    file: UploadFile = File(...),
    allow_external_vision: bool = Query(
        False, description="The person's yes to an AI model outside the household's network"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Read a workshop invoice, job card or quote (PDF or photo) into a draft
    service visit. Writes nothing: the form fills from the draft and the
    person saves.

    **Raises:**
    - **409** ``ai_reading_not_configured``: AI document reading is off
    - **409** ``{"code": "vision_consent_required", "host"}``: the model is
      outside the network and ``allow_external_vision`` was not set
    - **413**: the file is too large
    - **502**: the AI endpoint failed
    """
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db, require_write=True)

    # Size from the spooled file before reading it into memory (see fuel.py).
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)
    if file_size > MAX_INVOICE_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Invoice file exceeds maximum of {MAX_INVOICE_UPLOAD_BYTES // (1024 * 1024)}MB",
        )
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The file is empty")

    result = await read_service_invoice(
        db,
        file_bytes=file_bytes,
        filename=file.filename,
        content_type=file.content_type,
        user=current_user,
        allow_external_vision=allow_external_vision,
    )
    return ServiceInvoiceReadResponse.model_validate(result)

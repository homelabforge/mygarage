"""Vendor CRUD API endpoints."""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.vendor import (
    VendorCreate,
    VendorListResponse,
    VendorPriceHistoryResponse,
    VendorResponse,
    VendorUpdate,
)
from app.services.auth import require_auth
from app.services.vendor_service import VendorService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vendors", tags=["Vendors"])


@router.get("", response_model=VendorListResponse)
async def list_vendors(
    search: str | None = Query(None, description="Search vendors by name"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=500, description="Maximum records to return"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get all vendors with optional search.

    **Query Parameters:**
    - **search**: Optional search term for vendor name
    - **skip**: Number of records to skip (pagination)
    - **limit**: Maximum number of records to return

    **Returns:**
    - List of vendors with total count
    """
    service = VendorService(db)
    vendors, total = await service.list_vendors(current_user, skip, limit, search)
    return VendorListResponse(vendors=vendors, total=total)


@router.get("/{vendor_id}", response_model=VendorResponse)
async def get_vendor(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get a specific vendor by ID.

    **Path Parameters:**
    - **vendor_id**: Vendor ID

    **Returns:**
    - Vendor details

    **Raises:**
    - **404**: Vendor not found
    """
    service = VendorService(db)
    vendor = await service.get_vendor(vendor_id, current_user)
    return VendorResponse(
        id=vendor.id,
        name=vendor.name,
        address=vendor.address,
        city=vendor.city,
        state=vendor.state,
        zip_code=vendor.zip_code,
        phone=vendor.phone,
        created_at=vendor.created_at,
        updated_at=vendor.updated_at,
        full_address=vendor.full_address,
    )


@router.post("", response_model=VendorResponse, status_code=201)
async def create_vendor(
    vendor_data: VendorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Create a new vendor.

    **Request Body:**
    - Vendor data

    **Returns:**
    - Created vendor

    **Raises:**
    - **409**: Vendor with this name already exists
    """
    service = VendorService(db)
    vendor = await service.create_vendor(vendor_data, current_user)
    return VendorResponse(
        id=vendor.id,
        name=vendor.name,
        address=vendor.address,
        city=vendor.city,
        state=vendor.state,
        zip_code=vendor.zip_code,
        phone=vendor.phone,
        created_at=vendor.created_at,
        updated_at=vendor.updated_at,
        full_address=vendor.full_address,
    )


@router.put("/{vendor_id}", response_model=VendorResponse)
async def update_vendor(
    vendor_id: int,
    vendor_data: VendorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Update an existing vendor.

    **Path Parameters:**
    - **vendor_id**: Vendor ID

    **Request Body:**
    - Vendor update data

    **Returns:**
    - Updated vendor

    **Raises:**
    - **404**: Vendor not found
    - **409**: Vendor with this name already exists
    """
    service = VendorService(db)
    vendor = await service.update_vendor(vendor_id, vendor_data, current_user)
    return VendorResponse(
        id=vendor.id,
        name=vendor.name,
        address=vendor.address,
        city=vendor.city,
        state=vendor.state,
        zip_code=vendor.zip_code,
        phone=vendor.phone,
        created_at=vendor.created_at,
        updated_at=vendor.updated_at,
        full_address=vendor.full_address,
    )


@router.delete("/{vendor_id}", status_code=204)
async def delete_vendor(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Delete a vendor.

    **Path Parameters:**
    - **vendor_id**: Vendor ID

    **Raises:**
    - **404**: Vendor not found
    - **409**: Cannot delete vendor with existing service visits
    """
    service = VendorService(db)
    await service.delete_vendor(vendor_id, current_user)
    return None


@router.get("/{vendor_id}/price-history", response_model=VendorPriceHistoryResponse)
async def get_vendor_price_history(
    vendor_id: int,
    schedule_item_id: int | None = Query(
        None, description="Filter by schedule item ID"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get price history for a vendor.

    **Path Parameters:**
    - **vendor_id**: Vendor ID

    **Query Parameters:**
    - **schedule_item_id**: Optional filter by schedule item

    **Returns:**
    - Price history with statistics (average, min, max)
    """
    service = VendorService(db)
    return await service.get_price_history(vendor_id, current_user, schedule_item_id)

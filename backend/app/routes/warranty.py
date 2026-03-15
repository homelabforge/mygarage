"""Warranty record API routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.warranty import (
    WarrantyRecord,
    WarrantyRecordCreate,
    WarrantyRecordUpdate,
)
from app.services.auth import require_auth
from app.services.warranty_service import WarrantyService

router = APIRouter(prefix="/api", tags=["Warranties"])


@router.get("/vehicles/{vin}/warranties", response_model=list[WarrantyRecord])
async def get_warranties(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Get all warranty records for a vehicle."""
    service = WarrantyService(db)
    return await service.list_warranties(vin, current_user)


@router.post("/vehicles/{vin}/warranties", response_model=WarrantyRecord, status_code=201)
async def create_warranty(
    vin: str,
    warranty: WarrantyRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Create a new warranty record."""
    service = WarrantyService(db)
    return await service.create_warranty(vin, warranty, current_user)


@router.get("/vehicles/{vin}/warranties/{warranty_id}", response_model=WarrantyRecord)
async def get_warranty(
    vin: str,
    warranty_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Get a specific warranty record."""
    service = WarrantyService(db)
    return await service.get_warranty(vin, warranty_id, current_user)


@router.put("/vehicles/{vin}/warranties/{warranty_id}", response_model=WarrantyRecord)
async def update_warranty(
    vin: str,
    warranty_id: int,
    warranty_update: WarrantyRecordUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Update a warranty record."""
    service = WarrantyService(db)
    return await service.update_warranty(vin, warranty_id, warranty_update, current_user)


@router.delete("/vehicles/{vin}/warranties/{warranty_id}", status_code=204)
async def delete_warranty(
    vin: str,
    warranty_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Delete a warranty record."""
    service = WarrantyService(db)
    await service.delete_warranty(vin, warranty_id, current_user)
    return None

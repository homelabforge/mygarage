"""Tax/registration record routes for MyGarage API."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.tax import (
    TaxRecordCreate,
    TaxRecordListResponse,
    TaxRecordResponse,
    TaxRecordUpdate,
)
from app.services.auth import require_auth
from app.services.tax_service import TaxRecordService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vehicles", tags=["tax-records"])


@router.get("/{vin}/tax-records", response_model=TaxRecordListResponse)
async def list_tax_records(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> TaxRecordListResponse:
    """List all tax/registration records for a vehicle."""
    service = TaxRecordService(db)
    return await service.list_records(vin, current_user)


@router.post("/{vin}/tax-records", response_model=TaxRecordResponse, status_code=201)
async def create_tax_record(
    vin: str,
    record_data: TaxRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> TaxRecordResponse:
    """Create a new tax/registration record."""
    service = TaxRecordService(db)
    return await service.create_record(vin, record_data, current_user)


@router.get("/{vin}/tax-records/{record_id}", response_model=TaxRecordResponse)
async def get_tax_record(
    vin: str,
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> TaxRecordResponse:
    """Get a specific tax/registration record."""
    service = TaxRecordService(db)
    return await service.get_record(vin, record_id, current_user)


@router.put("/{vin}/tax-records/{record_id}", response_model=TaxRecordResponse)
async def update_tax_record(
    vin: str,
    record_id: int,
    update_data: TaxRecordUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> TaxRecordResponse:
    """Update a tax/registration record."""
    service = TaxRecordService(db)
    return await service.update_record(vin, record_id, update_data, current_user)


@router.delete("/{vin}/tax-records/{record_id}", status_code=204)
async def delete_tax_record(
    vin: str,
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> None:
    """Delete a tax/registration record."""
    service = TaxRecordService(db)
    await service.delete_record(vin, record_id, current_user)

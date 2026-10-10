"""Financing record CRUD API endpoints."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.financing import (
    FinancingRecordCreate,
    FinancingRecordListResponse,
    FinancingRecordResponse,
    FinancingRecordUpdate,
)
from app.services.auth import require_auth
from app.services.financing_service import FinancingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vehicles/{vin}/financing-records", tags=["Financing"])


@router.get("", response_model=FinancingRecordListResponse)
async def list_financing_records(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> FinancingRecordListResponse:
    """Get all financing records for a vehicle."""
    service = FinancingService(db)
    return await service.list_records(vin, current_user)


@router.post("", response_model=FinancingRecordResponse, status_code=201)
async def create_financing_record(
    vin: str,
    record: FinancingRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> FinancingRecordResponse:
    """Create a new financing record for a vehicle."""
    service = FinancingService(db)
    return await service.create_record(vin, record, current_user)


@router.get("/{record_id}", response_model=FinancingRecordResponse)
async def get_financing_record(
    vin: str,
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> FinancingRecordResponse:
    """Get a specific financing record."""
    service = FinancingService(db)
    return await service.get_record(vin, record_id, current_user)


@router.put("/{record_id}", response_model=FinancingRecordResponse)
async def update_financing_record(
    vin: str,
    record_id: int,
    record_update: FinancingRecordUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> FinancingRecordResponse:
    """Update a financing record."""
    service = FinancingService(db)
    return await service.update_record(vin, record_id, record_update, current_user)


@router.delete("/{record_id}", status_code=204)
async def delete_financing_record(
    vin: str,
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> None:
    """Delete a financing record."""
    service = FinancingService(db)
    await service.delete_record(vin, record_id, current_user)

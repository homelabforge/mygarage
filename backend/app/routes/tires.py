"""Tire tracking API routes."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.tire import (
    TireCreate,
    TireListResponse,
    TireReadingCreate,
    TireResponse,
    TireUpdate,
)
from app.services.auth import require_auth
from app.services.tire_service import TireService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vehicles", tags=["tires"])


@router.get("/{vin}/tires", response_model=TireListResponse)
async def list_tires(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> TireListResponse:
    """List tires (all positions) for a vehicle with wear projections."""
    return await TireService(db).list_tires(vin, current_user)


@router.post("/{vin}/tires", response_model=TireResponse, status_code=201)
async def upsert_tire(
    vin: str,
    data: TireCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> TireResponse:
    """Create or replace the tire at a given position."""
    return await TireService(db).upsert_tire(vin, data, current_user)


@router.put("/{vin}/tires/{tire_id}", response_model=TireResponse)
async def update_tire(
    vin: str,
    tire_id: int,
    data: TireUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> TireResponse:
    """Update tire metadata / latest tread without adding a history reading."""
    return await TireService(db).update_tire(vin, tire_id, data, current_user)


@router.delete("/{vin}/tires/{tire_id}", status_code=204)
async def delete_tire(
    vin: str,
    tire_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> None:
    """Remove a tire position record and its readings."""
    await TireService(db).delete_tire(vin, tire_id, current_user)


@router.post(
    "/{vin}/tires/{tire_id}/readings",
    response_model=TireResponse,
    status_code=201,
)
async def add_tire_reading(
    vin: str,
    tire_id: int,
    data: TireReadingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> TireResponse:
    """Append a tread/pressure reading and refresh wear projection + reminders."""
    return await TireService(db).add_reading(vin, tire_id, data, current_user)

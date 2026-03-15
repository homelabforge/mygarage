"""Spot rental routes for MyGarage API."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.spot_rental import (
    SpotRentalCreate,
    SpotRentalListResponse,
    SpotRentalResponse,
    SpotRentalUpdate,
)
from app.services.auth import require_auth
from app.services.spot_rental_service import SpotRentalService

router = APIRouter(prefix="/api/vehicles", tags=["spot-rentals"])


@router.get("/{vin}/spot-rentals", response_model=SpotRentalListResponse)
async def list_spot_rentals(
    vin: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
) -> SpotRentalListResponse:
    """List all spot rentals for a vehicle."""
    service = SpotRentalService(db)
    return await service.list_rentals(vin, current_user)


@router.post("/{vin}/spot-rentals", response_model=SpotRentalResponse, status_code=201)
async def create_spot_rental(
    vin: str,
    rental_data: SpotRentalCreate,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
) -> SpotRentalResponse:
    """Create a new spot rental record."""
    service = SpotRentalService(db)
    return await service.create_rental(vin, rental_data, current_user)


@router.get("/{vin}/spot-rentals/{rental_id}", response_model=SpotRentalResponse)
async def get_spot_rental(
    vin: str,
    rental_id: int,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
) -> SpotRentalResponse:
    """Get a specific spot rental record."""
    service = SpotRentalService(db)
    return await service.get_rental(vin, rental_id, current_user)


@router.put("/{vin}/spot-rentals/{rental_id}", response_model=SpotRentalResponse)
async def update_spot_rental(
    vin: str,
    rental_id: int,
    update_data: SpotRentalUpdate,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
) -> SpotRentalResponse:
    """Update a spot rental record."""
    service = SpotRentalService(db)
    return await service.update_rental(vin, rental_id, update_data, current_user)


@router.delete("/{vin}/spot-rentals/{rental_id}", status_code=204)
async def delete_spot_rental(
    vin: str,
    rental_id: int,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: User | None = Depends(require_auth),
) -> None:
    """Delete a spot rental record."""
    service = SpotRentalService(db)
    await service.delete_rental(vin, rental_id, current_user)

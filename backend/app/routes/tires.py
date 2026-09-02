"""Tire tracking API routes."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.tire import (
    TireCreate,
    TireCreateAndMountRequest,
    TireDismountRequest,
    TireListResponse,
    TireMountRequest,
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
async def create_tire(
    vin: str,
    data: TireCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> TireResponse:
    """Create a tire. It is not mounted until you mount it.

    **Breaking in v3.3.0.** This used to take a `position` and upsert by
    `(vin, position)`. It no longer accepts `position` at all, and a payload
    carrying one is rejected with 422 rather than silently creating a second,
    unmounted tire. Create then mount, or use the create-and-mount endpoint.
    """
    return await TireService(db).create_tire(vin, data, current_user)


@router.post("/{vin}/tires/create-and-mount", response_model=TireResponse, status_code=201)
async def create_and_mount_tire(
    vin: str,
    data: TireCreateAndMountRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> TireResponse:
    """Create a tire and mount it in one step.

    Atomic: if the corner is occupied the whole operation fails with 409 and
    no tire is created. Doing the two calls by hand and losing the second
    leaves an orphan tire the caller did not ask for.
    """
    return await TireService(db).create_and_mount(vin, data, current_user)


@router.post("/{vin}/tires/{tire_id}/mount", response_model=TireResponse)
async def mount_tire(
    vin: str,
    tire_id: int,
    data: TireMountRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> TireResponse:
    """Mount a stored tire at a position, opening a mount period.

    409 if this tire is already mounted, or if another tire holds that corner.
    """
    return await TireService(db).mount_tire(vin, tire_id, data, current_user)


@router.post("/{vin}/tires/{tire_id}/dismount", response_model=TireResponse)
async def dismount_tire(
    vin: str,
    tire_id: int,
    data: TireDismountRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> TireResponse:
    """Take a tire off the vehicle, closing its open mount period.

    The tire keeps its readings and its history; it simply has no position.
    """
    return await TireService(db).dismount_tire(vin, tire_id, data, current_user)


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

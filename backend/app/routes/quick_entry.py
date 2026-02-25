"""Quick Entry API — lightweight vehicle list for mobile quick logging."""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_share import VehicleShare
from app.services.auth import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/quick-entry", tags=["Quick Entry"])


class QuickEntryVehicle(BaseModel):
    """Lightweight vehicle summary for the Quick Entry selector."""

    vin: str
    nickname: str
    year: int | None
    make: str | None
    model: str | None
    vehicle_type: str
    thumbnail_url: str | None

    class Config:
        from_attributes = True


class QuickEntryVehicleList(BaseModel):
    """Response for the quick-entry vehicle list."""

    vehicles: list[QuickEntryVehicle]


@router.get("/vehicles", response_model=QuickEntryVehicleList)
async def list_quick_entry_vehicles(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> QuickEntryVehicleList:
    """Return writable, non-archived vehicles for the Quick Entry page.

    Returns vehicles the current user:
    - Owns (user_id matches), OR
    - Has write-share access to

    Excludes archived vehicles in both cases.
    """
    # Owned, non-archived vehicles
    owned_result = await db.execute(
        select(Vehicle).where(
            Vehicle.user_id == current_user.id,
            Vehicle.archived_at.is_(None),
        )
    )
    owned = list(owned_result.scalars().all())

    # Write-shared, non-archived vehicles (exclude already-owned to avoid duplicates)
    owned_vins = {v.vin for v in owned}
    shared_query = (
        select(Vehicle)
        .join(
            VehicleShare,
            VehicleShare.vehicle_vin == Vehicle.vin,
        )
        .where(
            VehicleShare.user_id == current_user.id,
            VehicleShare.permission == "write",
            Vehicle.archived_at.is_(None),
        )
    )
    if owned_vins:
        shared_query = shared_query.where(Vehicle.vin.not_in(owned_vins))
    shared_result = await db.execute(shared_query)
    shared = list(shared_result.scalars().all())

    all_vehicles = owned + shared

    result = []
    for vehicle in all_vehicles:
        thumbnail_url: str | None = None
        if vehicle.main_photo:
            filename = Path(vehicle.main_photo).name
            thumbnail_url = f"/api/vehicles/{vehicle.vin}/photos/{filename}"

        result.append(
            QuickEntryVehicle(
                vin=vehicle.vin,
                nickname=vehicle.nickname,
                year=vehicle.year,
                make=vehicle.make,
                model=vehicle.model,
                vehicle_type=vehicle.vehicle_type,
                thumbnail_url=thumbnail_url,
            )
        )

    return QuickEntryVehicleList(vehicles=result)

"""Quick Entry API — lightweight vehicle list for mobile quick logging."""

import logging
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_share import VehicleShare
from app.schemas.vehicle import LenientUsageUnit, LenientVehicleType
from app.services.auth import require_auth
from app.utils.unit_resolution import LenientDistanceUnit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/quick-entry", tags=["Quick Entry"])


class QuickEntryVehicle(BaseModel):
    """Lightweight vehicle summary for the Quick Entry selector."""

    vin: str
    nickname: str
    year: int | None
    make: str | None
    model: str | None
    vehicle_type: LenientVehicleType
    # Both fuel slots: DEF is offered only where the API accepts it, a diesel
    # in either slot (`app.utils.def_sync`).
    fuel_type: str | None = None
    fuel_type_secondary: str | None = None
    usage_unit: LenientUsageUnit = "distance"
    secondary_usage_enabled: bool = False
    # The vehicle's own odometer unit, so a Quick Entry form opens in it (#172).
    distance_unit: LenientDistanceUnit = None
    thumbnail_url: str | None

    model_config = ConfigDict(from_attributes=True)


class QuickEntryVehicleList(BaseModel):
    """Response for the quick-entry vehicle list."""

    vehicles: list[QuickEntryVehicle]


@router.get("/vehicles", response_model=QuickEntryVehicleList)
async def list_quick_entry_vehicles(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> QuickEntryVehicleList:
    """Return writable, non-archived vehicles for the Quick Entry page.

    Returns vehicles the current user:
    - Owns (user_id matches), OR
    - Has write-share access to

    Excludes archived vehicles in both cases.

    When auth is disabled (``auth_mode='none'`` — ``require_auth`` returns
    ``None``), there is no user to scope to, so all non-archived vehicles are
    returned, matching ``VehicleService.list_vehicles``.
    """
    if current_user is None:
        all_result = await db.execute(select(Vehicle).where(Vehicle.archived_at.is_(None)))
        all_vehicles = list(all_result.scalars().all())
    else:
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
                vehicle_type=vehicle.vehicle_type,  # pyright: ignore[reportArgumentType]  # lenient vocab reads the stored str
                fuel_type=vehicle.fuel_type,
                fuel_type_secondary=vehicle.fuel_type_secondary,
                usage_unit=vehicle.usage_unit or "distance",  # pyright: ignore[reportArgumentType]  # lenient vocab reads the stored str
                secondary_usage_enabled=bool(vehicle.secondary_usage_enabled),
                distance_unit=vehicle.distance_unit,  # pyright: ignore[reportArgumentType]  # lenient vocab reads the stored str
                thumbnail_url=thumbnail_url,
            )
        )

    return QuickEntryVehicleList(vehicles=result)

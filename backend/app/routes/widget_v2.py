"""Read-only metric+imperial widget endpoints (v2) polled by dashboards.

Same auth, rate limiting, ownership scoping, and 404-not-403 semantics as
/api/widget/* (v1). v2 returns BOTH unit systems per vehicle; summary and
vehicle-list are unit-agnostic and reuse the v1 schemas/service methods.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.widget_api_key import WidgetApiKey
from app.schemas.widget import WidgetSummary, WidgetVehicleList, WidgetVehicleV2
from app.services.widget_aggregation import WidgetAggregationService
from app.services.widget_auth import (
    WIDGET_RATE_LIMIT,
    require_widget_key,
    widget_key_func,
    widget_limiter,
)
from app.utils.unit_resolution import resolve_units

router = APIRouter(prefix="/api/v2/widget", tags=["widget-v2"])


@router.get("/summary", response_model=WidgetSummary)
@widget_limiter.limit(WIDGET_RATE_LIMIT, key_func=widget_key_func)
async def get_summary(
    request: Request,
    user_key: tuple[User, WidgetApiKey] = Depends(require_widget_key),
    db: AsyncSession = Depends(get_db),
) -> WidgetSummary:
    """Aggregate counts across all vehicles the key can see (unit-agnostic)."""
    user, key = user_key
    service = WidgetAggregationService(db)
    return await service.summary(user.id, allowed_vins=key.allowed_vins)


@router.get("/vehicles", response_model=WidgetVehicleList)
@widget_limiter.limit(WIDGET_RATE_LIMIT, key_func=widget_key_func)
async def list_widget_vehicles(
    request: Request,
    user_key: tuple[User, WidgetApiKey] = Depends(require_widget_key),
    db: AsyncSession = Depends(get_db),
) -> WidgetVehicleList:
    """VIN + label pairs for the key's accessible vehicles (unit-agnostic)."""
    user, key = user_key
    service = WidgetAggregationService(db)
    vehicles = await service.list_vehicles(user.id, allowed_vins=key.allowed_vins)
    return WidgetVehicleList(vehicles=vehicles)


@router.get("/vehicle/{vin}", response_model=WidgetVehicleV2)
@widget_limiter.limit(WIDGET_RATE_LIMIT, key_func=widget_key_func)
async def get_widget_vehicle(
    vin: str,
    request: Request,
    user_key: tuple[User, WidgetApiKey] = Depends(require_widget_key),
    db: AsyncSession = Depends(get_db),
) -> WidgetVehicleV2:
    """Per-vehicle rollup in both unit systems. 404 (not 403) for out-of-scope VINs."""
    # D7: resolve the key OWNER's unit set and pass it in, exactly as
    # `routes/widget.py` does (see the fuller note there). The two modules call
    # different service methods, so threading the context through one and not
    # the other would leave this endpoint on the instance-wide default.
    user, key = user_key
    service = WidgetAggregationService(db)
    result = await service.vehicle_v2(
        user.id, vin, allowed_vins=key.allowed_vins, units=resolve_units(user)
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return result

"""Read-only widget endpoints polled by gethomepage and similar dashboards.

Every route authenticates via `require_widget_key` (401 on any failure,
including auth_mode=none) and is rate-limited to `WIDGET_RATE_LIMIT` per
widget-key bucket via slowapi.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.models.widget_api_key import WidgetApiKey
from app.schemas.widget import WidgetSummary, WidgetVehicle, WidgetVehicleList
from app.services.widget_aggregation import WidgetAggregationService
from app.services.widget_auth import (
    WIDGET_RATE_LIMIT,
    require_widget_key,
    widget_key_func,
    widget_limiter,
)

router = APIRouter(prefix="/api/widget", tags=["widget"])


@router.get("/summary", response_model=WidgetSummary)
@widget_limiter.limit(WIDGET_RATE_LIMIT, key_func=widget_key_func)
async def get_summary(
    request: Request,
    user_key: tuple[User, WidgetApiKey] = Depends(require_widget_key),
    db: AsyncSession = Depends(get_db),
) -> WidgetSummary:
    """Aggregate counts across all vehicles the key can see."""
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
    """VIN + label pairs for the key's accessible vehicles."""
    user, key = user_key
    service = WidgetAggregationService(db)
    vehicles = await service.list_vehicles(user.id, allowed_vins=key.allowed_vins)
    return WidgetVehicleList(vehicles=vehicles)


@router.get("/vehicle/{vin}", response_model=WidgetVehicle)
@widget_limiter.limit(WIDGET_RATE_LIMIT, key_func=widget_key_func)
async def get_widget_vehicle(
    vin: str,
    request: Request,
    user_key: tuple[User, WidgetApiKey] = Depends(require_widget_key),
    db: AsyncSession = Depends(get_db),
) -> WidgetVehicle:
    """Per-vehicle rollup. Returns 404 (not 403) for out-of-scope VINs to
    avoid confirming their existence."""
    user, key = user_key
    service = WidgetAggregationService(db)
    result = await service.vehicle(user.id, vin, allowed_vins=key.allowed_vins)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return result

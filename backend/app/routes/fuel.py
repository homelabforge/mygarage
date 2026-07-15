"""Fuel Record CRUD API endpoints with MPG calculation."""

import logging
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.drive_session import DriveSession
from app.models.user import User
from app.schemas.fuel import (
    FuelRecordCreate,
    FuelRecordListResponse,
    FuelRecordResponse,
    FuelRecordUpdate,
    ObcSuggestionResponse,
)
from app.services.auth import get_vehicle_or_403, require_auth
from app.services.fuel_service import FuelRecordService, build_fuel_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vehicles/{vin}/fuel", tags=["Fuel Records"])


@router.get("", response_model=FuelRecordListResponse)
async def list_fuel_records(
    vin: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    include_hauling: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get all fuel records for a vehicle with MPG calculations.

    **Path Parameters:**
    - **vin**: Vehicle VIN

    **Query Parameters:**
    - **skip**: Number of records to skip (pagination)
    - **limit**: Maximum number of records to return
    - **include_hauling**: Include towing/hauling records in MPG calculation (default: False)

    **Returns:**
    - List of fuel records with MPG and average MPG

    **Security:**
    - Users can only access fuel records for their own vehicles
    - Admin users can access all fuel records
    """
    service = FuelRecordService(db)
    responses, total, avg_value = await service.list_fuel_records(
        vin, current_user, skip, limit, include_hauling
    )

    return FuelRecordListResponse(records=responses, total=total, average_l_per_100km=avg_value)


# Maximum window between a DriveSession's `ended_at` and the fuel record's
# `filled_at` for OBC auto-suggest. Keeps suggestions tightly coupled to the
# drive that immediately preceded the fill-up.
OBC_SUGGESTION_WINDOW = timedelta(hours=24)


# IMPORTANT: must be declared BEFORE `/{record_id}` so FastAPI's declaration-
# order routing doesn't try to parse "obc-suggestion" as an int record_id.
@router.get("/obc-suggestion", response_model=ObcSuggestionResponse)
async def obc_suggestion(
    vin: str,
    at: datetime = Query(
        ...,
        description=(
            "Fill-up timestamp (naive local). Returns the most recent "
            "DriveSession that ended on or before this time within a 24-hour window."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> ObcSuggestionResponse:
    """Return OBC values from the DriveSession that immediately preceded a fill-up.

    Used by the fuel form's "Auto-fill from last drive" button. Always
    returns 404 when there's no usable session — the frontend then hides
    the button entirely.
    """
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db)

    cutoff = at - OBC_SUGGESTION_WINDOW
    result = await db.execute(
        select(DriveSession)
        .where(DriveSession.vin == vin)
        .where(DriveSession.ended_at.isnot(None))
        .where(DriveSession.ended_at <= at)
        .where(DriveSession.ended_at >= cutoff)
        .where(DriveSession.distance_km.isnot(None))
        .order_by(DriveSession.ended_at.desc())
        .limit(1)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(
            status_code=404,
            detail="No matching drive session within the 24-hour window",
        )

    # Compute L/100km from session aggregates when fuel_used_estimate is set.
    obc_l_per_100km: Decimal | None = None
    if (
        session.fuel_used_estimate is not None
        and session.distance_km is not None
        and session.distance_km > 0
    ):
        try:
            obc_l_per_100km = (
                Decimal(str(session.fuel_used_estimate))
                / Decimal(str(session.distance_km))
                * Decimal("100")
            ).quantize(Decimal("0.01"))
        except Exception:
            obc_l_per_100km = None

    avg_speed = (
        Decimal(str(session.avg_speed)).quantize(Decimal("0.1"))
        if session.avg_speed is not None
        else None
    )
    distance = (
        Decimal(str(session.distance_km)).quantize(Decimal("0.01"))
        if session.distance_km is not None
        else None
    )

    return ObcSuggestionResponse(
        session_id=session.id,
        ended_at=session.ended_at,
        distance_km=distance,
        obc_l_per_100km=obc_l_per_100km,
        obc_avg_speed_kmh=avg_speed,
        obc_trip_duration_s=session.duration_seconds,
    )


@router.get("/{record_id}", response_model=FuelRecordResponse)
async def get_fuel_record(
    vin: str,
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get a specific fuel record with MPG calculation.

    **Path Parameters:**
    - **vin**: Vehicle VIN
    - **record_id**: Fuel record ID

    **Returns:**
    - Fuel record details with MPG

    **Raises:**
    - **404**: Record not found
    - **403**: Not authorized

    **Security:**
    - Users can only access fuel records for their own vehicles
    - Admin users can access all fuel records
    """
    service = FuelRecordService(db)
    record, mpg = await service.get_fuel_record(vin, record_id, current_user)

    return await build_fuel_response(db, record, mpg)


@router.post("", response_model=FuelRecordResponse, status_code=201)
async def create_fuel_record(
    vin: str,
    record_data: FuelRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Create a new fuel record with MPG calculation.

    **Security:**
    - Users can only create fuel records for their own vehicles
    - Admin users can create fuel records for all vehicles
    """
    service = FuelRecordService(db)
    record, mpg = await service.create_fuel_record(vin, record_data, current_user)

    return await build_fuel_response(db, record, mpg)


@router.put("/{record_id}", response_model=FuelRecordResponse)
async def update_fuel_record(
    vin: str,
    record_id: int,
    record_data: FuelRecordUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Update an existing fuel record.

    **Security:**
    - Users can only update fuel records for their own vehicles
    - Admin users can update all fuel records
    """
    service = FuelRecordService(db)
    record, mpg = await service.update_fuel_record(vin, record_id, record_data, current_user)

    return await build_fuel_response(db, record, mpg)


@router.delete("/{record_id}", status_code=204)
async def delete_fuel_record(
    vin: str,
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Delete a fuel record.

    **Security:**
    - Users can only delete fuel records for their own vehicles
    - Admin users can delete all fuel records
    """
    service = FuelRecordService(db)
    await service.delete_fuel_record(vin, record_id, current_user)

    return None

"""Vehicle CRUD API endpoints."""

import logging
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.vehicle import TrailerDetails, Vehicle
from app.models.user import User
from app.schemas.vehicle import (
    VehicleCreate,
    VehicleUpdate,
    VehicleResponse,
    VehicleListResponse,
    TrailerDetailsCreate,
    TrailerDetailsUpdate,
    TrailerDetailsResponse,
    VehicleArchiveRequest,
)
from app.services.auth import require_auth, optional_auth
from app.services.vehicle_service import VehicleService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/vehicles", tags=["Vehicles"])


def sanitize_for_log(value: str) -> str:
    """
    Sanitize a string for safe logging by removing characters that could be used for log injection.

    Removes newline characters (\n, \r) that could allow a malicious user to forge log entries.

    Args:
        value: The string to sanitize

    Returns:
        Sanitized string safe for logging
    """
    if not value:
        return value
    return value.replace("\r\n", "").replace("\r", "").replace("\n", "")


@router.get("", response_model=VehicleListResponse)
async def list_vehicles(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get list of all vehicles.

    **Query Parameters:**
    - **skip**: Number of records to skip (pagination)
    - **limit**: Maximum number of records to return

    **Returns:**
    - List of vehicles with total count

    **Security:**
    - Users see only their own vehicles
    - Admin users see all vehicles
    """
    service = VehicleService(db)
    vehicles, total = await service.list_vehicles(current_user, skip, limit)

    return VehicleListResponse(
        vehicles=[VehicleResponse.model_validate(v) for v in vehicles], total=total
    )


@router.get("/{vin}", response_model=VehicleResponse)
async def get_vehicle(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get a specific vehicle by VIN.

    **Args:**
    - **vin**: 17-character Vehicle Identification Number

    **Returns:**
    - Vehicle details

    **Raises:**
    - **404**: Vehicle not found
    - **403**: Not authorized to access this vehicle

    **Security:**
    - Users can only access their own vehicles
    - Admin users can access all vehicles
    """
    service = VehicleService(db)
    vehicle = await service.get_vehicle(vin, current_user)

    return VehicleResponse.model_validate(vehicle)


@router.post("", response_model=VehicleResponse, status_code=201)
async def create_vehicle(
    vehicle_data: VehicleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Create a new vehicle.

    **Args:**
    - **vehicle_data**: Vehicle information including VIN

    **Returns:**
    - Created vehicle details

    **Raises:**
    - **400**: VIN already exists
    - **500**: Database error

    **Security:**
    - Vehicle is automatically assigned to the creating user
    - Admin users can also create vehicles
    """
    service = VehicleService(db)
    vehicle = await service.create_vehicle(vehicle_data, current_user)

    return VehicleResponse.model_validate(vehicle)


@router.put("/{vin}", response_model=VehicleResponse)
async def update_vehicle(
    vin: str,
    vehicle_data: VehicleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Update an existing vehicle.

    **Args:**
    - **vin**: Vehicle VIN to update
    - **vehicle_data**: Updated vehicle information

    **Returns:**
    - Updated vehicle details

    **Raises:**
    - **404**: Vehicle not found
    - **403**: Not authorized to update this vehicle
    - **500**: Database error

    **Security:**
    - Users can only update their own vehicles
    - Admin users can update all vehicles
    """
    service = VehicleService(db)
    vehicle = await service.update_vehicle(vin, vehicle_data, current_user)

    return VehicleResponse.model_validate(vehicle)


@router.delete("/{vin}", status_code=204)
async def delete_vehicle(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Delete a vehicle.

    **Args:**
    - **vin**: Vehicle VIN to delete

    **Raises:**
    - **404**: Vehicle not found
    - **403**: Not authorized to delete this vehicle
    - **500**: Database error

    **Security:**
    - Users can only delete their own vehicles
    - Admin users can delete all vehicles
    """
    service = VehicleService(db)
    await service.delete_vehicle(vin, current_user)

    return None


# Trailer Details endpoints


@router.get("/{vin}/trailer", response_model=TrailerDetailsResponse)
async def get_trailer_details(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Get trailer details for a vehicle.

    **Security:**
    - Users can only access trailer details for their own vehicles
    - Admin users can access all trailer details
    """
    from app.services.auth import get_vehicle_or_403

    vin = vin.upper().strip()

    # Check vehicle ownership first
    await get_vehicle_or_403(vin, current_user, db)

    result = await db.execute(select(TrailerDetails).where(TrailerDetails.vin == vin))
    trailer = result.scalar_one_or_none()

    if not trailer:
        raise HTTPException(
            status_code=404, detail=f"Trailer details not found for VIN {vin}"
        )

    return TrailerDetailsResponse.model_validate(trailer)


@router.post("/{vin}/trailer", response_model=TrailerDetailsResponse, status_code=201)
async def create_trailer_details(
    vin: str,
    trailer_data: TrailerDetailsCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Create trailer details for a vehicle.

    **Security:**
    - Users can only create trailer details for their own vehicles
    - Admin users can create trailer details for all vehicles
    """
    from app.services.auth import get_vehicle_or_403

    vin = vin.upper().strip()

    try:
        # Check vehicle ownership (raises 403 if unauthorized)
        _ = await get_vehicle_or_403(vin, current_user, db)

        # Check if trailer details already exist
        result = await db.execute(
            select(TrailerDetails).where(TrailerDetails.vin == vin)
        )
        existing = result.scalar_one_or_none()

        if existing:
            raise HTTPException(
                status_code=400, detail=f"Trailer details already exist for VIN {vin}"
            )

        # Create trailer details
        trailer_data.vin = vin
        trailer = TrailerDetails(**trailer_data.model_dump())
        db.add(trailer)
        await db.commit()
        await db.refresh(trailer)

        logger.info("Created trailer details for: %s", vin)

        return TrailerDetailsResponse.model_validate(trailer)

    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(
            "Database constraint violation creating trailer details for %s: %s", vin, e
        )
        raise HTTPException(
            status_code=409, detail=f"Trailer details already exist for VIN {vin}"
        )
    except OperationalError as e:
        await db.rollback()
        logger.error(
            "Database connection error creating trailer details for %s: %s", vin, e
        )
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")


@router.put("/{vin}/trailer", response_model=TrailerDetailsResponse)
async def update_trailer_details(
    vin: str,
    trailer_data: TrailerDetailsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Update trailer details for a vehicle.

    **Security:**
    - Users can only update trailer details for their own vehicles
    - Admin users can update trailer details for all vehicles
    """
    from app.services.auth import get_vehicle_or_403

    vin = vin.upper().strip()

    try:
        # Check vehicle ownership
        await get_vehicle_or_403(vin, current_user, db)

        # Get existing trailer details
        result = await db.execute(
            select(TrailerDetails).where(TrailerDetails.vin == vin)
        )
        trailer = result.scalar_one_or_none()

        if not trailer:
            raise HTTPException(
                status_code=404, detail=f"Trailer details not found for VIN {vin}"
            )

        # Update fields
        update_data = trailer_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(trailer, field, value)

        await db.commit()
        await db.refresh(trailer)

        logger.info("Updated trailer details for: %s", vin)

        return TrailerDetailsResponse.model_validate(trailer)

    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(
            "Database constraint violation updating trailer details for %s: %s", vin, e
        )
        raise HTTPException(status_code=409, detail="Database constraint violation")
    except OperationalError as e:
        await db.rollback()
        logger.error(
            "Database connection error updating trailer details for %s: %s", vin, e
        )
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")


# ========== ARCHIVE ENDPOINTS ==========


@router.post("/{vin}/archive", response_model=VehicleResponse)
async def archive_vehicle(
    vin: str,
    archive_data: VehicleArchiveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(optional_auth),
):
    """
    Archive a vehicle (soft delete).

    **Args:**
    - **vin**: Vehicle VIN
    - **archive_data**: Archive metadata (reason, price, date, notes, visible)

    **Returns:**
    - Updated vehicle with archive metadata

    **Raises:**
    - **404**: Vehicle not found
    - **403**: Not authorized (when authenticated)
    """
    vin = vin.upper().strip()
    service = VehicleService(db)

    # In auth mode, check ownership; in none mode, allow all
    if current_user:
        vehicle = await service.get_vehicle(vin, current_user)
    else:
        # No auth mode: get vehicle directly
        result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
        vehicle = result.scalar_one_or_none()
        if not vehicle:
            raise HTTPException(status_code=404, detail="Vehicle not found")

    # Set archive fields
    vehicle.archived_at = datetime.now(timezone.utc)
    vehicle.archive_reason = archive_data.reason
    vehicle.archive_sale_price = archive_data.sale_price
    vehicle.archive_sale_date = archive_data.sale_date
    vehicle.archive_notes = archive_data.notes
    vehicle.archived_visible = archive_data.visible

    await db.commit()
    await db.refresh(vehicle)

    logger.info(
        "Archived vehicle %s (reason: %s)",
        sanitize_for_log(vin),
        sanitize_for_log(archive_data.reason),
    )
    return VehicleResponse.model_validate(vehicle)


@router.post("/{vin}/unarchive", response_model=VehicleResponse)
async def unarchive_vehicle(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(optional_auth),
):
    """
    Restore an archived vehicle to active status.

    **Args:**
    - **vin**: Vehicle VIN

    **Returns:**
    - Updated vehicle (active)

    **Raises:**
    - **404**: Vehicle not found
    - **403**: Not authorized (when authenticated)
    - **400**: Vehicle is not archived
    """
    vin = vin.upper().strip()
    service = VehicleService(db)

    # In auth mode, check ownership; in none mode, allow all
    if current_user:
        vehicle = await service.get_vehicle(vin, current_user)
    else:
        # No auth mode: get vehicle directly
        result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
        vehicle = result.scalar_one_or_none()
        if not vehicle:
            raise HTTPException(status_code=404, detail="Vehicle not found")

    if not vehicle.archived_at:
        raise HTTPException(status_code=400, detail="Vehicle is not archived")

    # Clear archive fields
    vehicle.archived_at = None
    vehicle.archive_reason = None
    vehicle.archive_sale_price = None
    vehicle.archive_sale_date = None
    vehicle.archive_notes = None
    vehicle.archived_visible = True

    await db.commit()
    await db.refresh(vehicle)

    logger.info("Unarchived vehicle %s", sanitize_for_log(vin))
    return VehicleResponse.model_validate(vehicle)


@router.get("/archived/list", response_model=VehicleListResponse)
async def list_archived_vehicles(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(optional_auth),
):
    """
    Get list of archived vehicles (user's own only in auth mode, all in none mode).

    **Query Parameters:**
    - **skip**: Number of records to skip
    - **limit**: Maximum number of records to return

    **Returns:**
    - List of archived vehicles with total count

    **Security:**
    - When authenticated: Users see ONLY their own archived vehicles (admin does NOT see all)
    - When auth_mode=none: Returns all archived vehicles
    """
    # Build query for archived vehicles
    if current_user:
        # Auth mode: user's archived vehicles + vehicles with NULL user_id (created in none mode)
        logger.info(f"Fetching archived vehicles for user_id={current_user.id}")
        query = (
            select(Vehicle)
            .where(
                ((Vehicle.user_id == current_user.id) | (Vehicle.user_id.is_(None))),
                Vehicle.archived_at.isnot(None),
            )
            .order_by(Vehicle.archived_at.desc())
        )
    else:
        # No auth mode: all archived vehicles
        logger.info("Fetching all archived vehicles (auth_mode=none)")
        query = (
            select(Vehicle)
            .where(Vehicle.archived_at.isnot(None))
            .order_by(Vehicle.archived_at.desc())
        )

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    result = await db.execute(count_query)
    total = result.scalar() or 0

    logger.info(f"Found {total} archived vehicles")

    # Get paginated results
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    vehicles = result.scalars().all()

    logger.info(f"Returning {len(vehicles)} archived vehicles")

    return VehicleListResponse(
        vehicles=[VehicleResponse.model_validate(v) for v in vehicles], total=total
    )


@router.patch("/{vin}/archive/visibility", response_model=VehicleResponse)
async def toggle_archived_visibility(
    vin: str,
    visible: bool,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(optional_auth),
):
    """
    Toggle visibility of archived vehicle in main list.

    **Args:**
    - **vin**: Vehicle VIN
    - **visible**: Whether to show in main list

    **Returns:**
    - Updated vehicle

    **Raises:**
    - **404**: Vehicle not found
    - **403**: Not authorized (when authenticated)
    - **400**: Vehicle is not archived
    """
    vin = vin.upper().strip()
    service = VehicleService(db)

    # In auth mode, check ownership; in none mode, allow all
    if current_user:
        vehicle = await service.get_vehicle(vin, current_user)
    else:
        # No auth mode: get vehicle directly
        result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
        vehicle = result.scalar_one_or_none()
        if not vehicle:
            raise HTTPException(status_code=404, detail="Vehicle not found")

    if not vehicle.archived_at:
        raise HTTPException(status_code=400, detail="Vehicle is not archived")

    vehicle.archived_visible = visible

    await db.commit()
    await db.refresh(vehicle)

    logger.info(
        "Set archived vehicle %s visibility to %s", sanitize_for_log(vin), visible
    )
    return VehicleResponse.model_validate(vehicle)

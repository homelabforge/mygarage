"""Vehicle CRUD API endpoints."""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.vehicle import TrailerDetails
from app.models.user import User
from app.schemas.vehicle import (
    VehicleCreate,
    VehicleUpdate,
    VehicleResponse,
    VehicleListResponse,
    TrailerDetailsCreate,
    TrailerDetailsUpdate,
    TrailerDetailsResponse,
)
from app.services.auth import require_auth
from app.services.vehicle_service import VehicleService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/vehicles", tags=["Vehicles"])


@router.get("", response_model=VehicleListResponse)
async def list_vehicles(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth)
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
        vehicles=[VehicleResponse.model_validate(v) for v in vehicles],
        total=total
    )


@router.get("/{vin}", response_model=VehicleResponse)
async def get_vehicle(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth)
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
    current_user: User = Depends(require_auth)
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
    current_user: User = Depends(require_auth)
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
    current_user: User = Depends(require_auth)
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
    current_user: User = Depends(require_auth)
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

    result = await db.execute(
        select(TrailerDetails).where(TrailerDetails.vin == vin)
    )
    trailer = result.scalar_one_or_none()

    if not trailer:
        raise HTTPException(status_code=404, detail=f"Trailer details not found for VIN {vin}")

    return TrailerDetailsResponse.model_validate(trailer)


@router.post("/{vin}/trailer", response_model=TrailerDetailsResponse, status_code=201)
async def create_trailer_details(
    vin: str,
    trailer_data: TrailerDetailsCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth)
):
    """Create trailer details for a vehicle.

    **Security:**
    - Users can only create trailer details for their own vehicles
    - Admin users can create trailer details for all vehicles
    """
    from app.services.auth import get_vehicle_or_403

    vin = vin.upper().strip()

    try:
        # Check vehicle ownership
        vehicle = await get_vehicle_or_403(vin, current_user, db)

        # Check if trailer details already exist
        result = await db.execute(
            select(TrailerDetails).where(TrailerDetails.vin == vin)
        )
        existing = result.scalar_one_or_none()

        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Trailer details already exist for VIN {vin}"
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
        logger.error("Database constraint violation creating trailer details for %s: %s", vin, e)
        raise HTTPException(status_code=409, detail=f"Trailer details already exist for VIN {vin}")
    except OperationalError as e:
        await db.rollback()
        logger.error("Database connection error creating trailer details for %s: %s", vin, e)
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")


@router.put("/{vin}/trailer", response_model=TrailerDetailsResponse)
async def update_trailer_details(
    vin: str,
    trailer_data: TrailerDetailsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth)
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
            raise HTTPException(status_code=404, detail=f"Trailer details not found for VIN {vin}")

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
        logger.error("Database constraint violation updating trailer details for %s: %s", vin, e)
        raise HTTPException(status_code=409, detail="Database constraint violation")
    except OperationalError as e:
        await db.rollback()
        logger.error("Database connection error updating trailer details for %s: %s", vin, e)
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")

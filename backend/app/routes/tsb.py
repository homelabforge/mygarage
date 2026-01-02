"""Technical Service Bulletin (TSB) API endpoints."""

import logging
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import Optional

from app.database import get_db
from app.models.tsb import TSB
from app.models.vehicle import Vehicle
from app.models.user import User
from app.schemas.tsb import (
    TSBCreate,
    TSBUpdate,
    TSBResponse,
    TSBListResponse,
    NHTSATSBSearchResponse,
)
from app.services.auth import require_auth
from app.services.nhtsa import NHTSAService

logger = logging.getLogger(__name__)

tsb_router = APIRouter(prefix="/api/tsbs", tags=["Technical Service Bulletins"])


@tsb_router.get("/vehicles/{vin}", response_model=TSBListResponse)
async def get_vehicle_tsbs(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Get all TSBs for a specific vehicle."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Get TSBs for this vehicle
    result = await db.execute(
        select(TSB).where(TSB.vin == vin).order_by(TSB.created_at.desc())
    )
    tsbs = result.scalars().all()

    return TSBListResponse(
        tsbs=[TSBResponse.model_validate(tsb) for tsb in tsbs],
        total=len(tsbs),
    )


@tsb_router.get("/vehicles/{vin}/check-nhtsa", response_model=NHTSATSBSearchResponse)
async def check_nhtsa_tsbs(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """
    Check NHTSA API for TSBs related to this vehicle.

    This queries the NHTSA TSB database by year/make/model and returns
    any available TSBs.
    """
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Query NHTSA API
    service = NHTSAService()
    try:
        tsbs = await service.get_vehicle_tsbs(vin, db)

        return NHTSATSBSearchResponse(
            found=len(tsbs) > 0,
            count=len(tsbs),
            tsbs=tsbs,
        )

    except ValueError as e:
        logger.error(f"Error fetching TSBs from NHTSA for {vin}: {e}")
        return NHTSATSBSearchResponse(
            found=False,
            count=0,
            tsbs=[],
            error=str(e),
        )
    except Exception as e:
        logger.error(f"Unexpected error fetching TSBs for {vin}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch TSBs: {str(e)}")


@tsb_router.post("/", response_model=TSBResponse, status_code=201)
async def create_tsb(
    tsb_data: TSBCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Create a new TSB record."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == tsb_data.vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Create TSB
    tsb = TSB(**tsb_data.model_dump())
    db.add(tsb)
    await db.commit()
    await db.refresh(tsb)

    logger.info(f"Created TSB {tsb.id} for vehicle {tsb_data.vin}")

    return TSBResponse.model_validate(tsb)


@tsb_router.put("/{tsb_id}", response_model=TSBResponse)
async def update_tsb(
    tsb_id: int,
    tsb_data: TSBUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Update an existing TSB record."""
    # Get TSB
    result = await db.execute(select(TSB).where(TSB.id == tsb_id))
    tsb = result.scalar_one_or_none()
    if not tsb:
        raise HTTPException(status_code=404, detail="TSB not found")

    # Update fields
    update_data = tsb_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(tsb, field, value)

    await db.commit()
    await db.refresh(tsb)

    logger.info(f"Updated TSB {tsb_id}")

    return TSBResponse.model_validate(tsb)


@tsb_router.delete("/{tsb_id}", status_code=204)
async def delete_tsb(
    tsb_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Delete a TSB record."""
    # Verify TSB exists
    result = await db.execute(select(TSB).where(TSB.id == tsb_id))
    tsb = result.scalar_one_or_none()
    if not tsb:
        raise HTTPException(status_code=404, detail="TSB not found")

    # Delete TSB
    await db.execute(delete(TSB).where(TSB.id == tsb_id))
    await db.commit()

    logger.info(f"Deleted TSB {tsb_id}")
    return None


@tsb_router.get("/{tsb_id}", response_model=TSBResponse)
async def get_tsb(
    tsb_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Get a specific TSB by ID."""
    result = await db.execute(select(TSB).where(TSB.id == tsb_id))
    tsb = result.scalar_one_or_none()
    if not tsb:
        raise HTTPException(status_code=404, detail="TSB not found")

    return TSBResponse.model_validate(tsb)

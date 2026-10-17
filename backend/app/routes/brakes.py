"""Brake tracking API routes (#202)."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.brake import (
    Axle,
    BrakeAxleUpdate,
    BrakeJobCreate,
    BrakeJobUpdate,
    BrakeMeasurementBatchCreate,
    BrakeMeasurementUpdate,
    BrakeOverviewResponse,
)
from app.services.auth import require_auth
from app.services.brake_service import BrakeService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vehicles", tags=["brakes"])


@router.get("/{vin}/brakes", response_model=BrakeOverviewResponse)
async def get_brakes(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> BrakeOverviewResponse:
    """A vehicle's brakes: both axles and the four corners, with wear estimates and history."""
    return await BrakeService(db).overview(vin, current_user)


@router.put("/{vin}/brakes/axles/{axle}", response_model=BrakeOverviewResponse)
async def update_brake_axle(
    vin: str,
    axle: Axle,
    data: BrakeAxleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> BrakeOverviewResponse:
    """Save an axle's setup: disc or drum, its minimum and new thickness, and the rotor or drum limit."""
    return await BrakeService(db).update_axle(vin, axle, data, current_user)


@router.post("/{vin}/brakes/measurements", response_model=BrakeOverviewResponse, status_code=201)
async def log_brake_measurements(
    vin: str,
    data: BrakeMeasurementBatchCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> BrakeOverviewResponse:
    """Record one to four corners measured on one day.

    Returns the whole overview: a measurement can move a corner's condition
    and its axle's reminder.
    """
    return await BrakeService(db).log_measurements(vin, data, current_user)


@router.put("/{vin}/brakes/measurements/{measurement_id}", response_model=BrakeOverviewResponse)
async def update_brake_measurement(
    vin: str,
    measurement_id: int,
    data: BrakeMeasurementUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> BrakeOverviewResponse:
    """Correct one measurement. Omitted keeps a field, null clears it."""
    return await BrakeService(db).update_measurement(vin, measurement_id, data, current_user)


@router.delete("/{vin}/brakes/measurements/{measurement_id}", status_code=204)
async def delete_brake_measurement(
    vin: str,
    measurement_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> None:
    """Delete one measurement."""
    await BrakeService(db).delete_measurement(vin, measurement_id, current_user)


@router.post("/{vin}/brakes/jobs", response_model=BrakeOverviewResponse, status_code=201)
async def create_brake_job(
    vin: str,
    data: BrakeJobCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> BrakeOverviewResponse:
    """Record a brake job on one to four corners.

    A pads or shoes job starts those corners' wear estimates over, from the
    new thickness when one is given.
    """
    return await BrakeService(db).create_job(vin, data, current_user)


@router.put("/{vin}/brakes/jobs/{job_id}", response_model=BrakeOverviewResponse)
async def update_brake_job(
    vin: str,
    job_id: int,
    data: BrakeJobUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> BrakeOverviewResponse:
    """Correct one corner's brake job. The new-pads measurement it wrote moves with it."""
    return await BrakeService(db).update_job(vin, job_id, data, current_user)


@router.delete("/{vin}/brakes/jobs/{job_id}", status_code=204)
async def delete_brake_job(
    vin: str,
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> None:
    """Delete one corner's brake job and the new-pads measurement it wrote."""
    await BrakeService(db).delete_job(vin, job_id, current_user)

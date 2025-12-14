"""Spot rental routes for MyGarage API."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import SpotRental, Vehicle
from app.models.spot_rental_billing import SpotRentalBilling
from app.models.user import User
from app.services.auth import require_auth
from app.schemas.spot_rental import (
    SpotRentalCreate,
    SpotRentalListResponse,
    SpotRentalResponse,
    SpotRentalUpdate,
)

router = APIRouter(prefix="/api/vehicles", tags=["spot-rentals"])


@router.get("/{vin}/spot-rentals", response_model=SpotRentalListResponse)
async def list_spot_rentals(
    vin: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Optional[User] = Depends(require_auth),
) -> SpotRentalListResponse:
    """List all spot rentals for a vehicle."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Get spot rentals ordered by check-in date descending
    # Eager-load billings to avoid N+1 queries
    query = (
        select(SpotRental)
        .where(SpotRental.vin == vin)
        .options(selectinload(SpotRental.billings))
        .order_by(SpotRental.check_in_date.desc())
    )
    result = await db.execute(query)
    rentals = result.scalars().all()

    # Get total count
    count_result = await db.execute(
        select(func.count()).select_from(SpotRental).where(SpotRental.vin == vin)
    )
    total = count_result.scalar_one()

    return SpotRentalListResponse(
        spot_rentals=[SpotRentalResponse.model_validate(r) for r in rentals],
        total=total,
    )


@router.post("/{vin}/spot-rentals", response_model=SpotRentalResponse, status_code=201)
async def create_spot_rental(
    vin: str,
    rental_data: SpotRentalCreate,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Optional[User] = Depends(require_auth),
) -> SpotRentalResponse:
    """Create a new spot rental record."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Verify vehicle is RV or Fifth Wheel (case-insensitive to match schema)
    vehicle_type = (vehicle.vehicle_type or "").replace(" ", "").lower()
    if vehicle_type not in {"rv", "fifthwheel"}:
        raise HTTPException(
            status_code=400,
            detail="Spot rentals are only available for RVs and Fifth Wheels",
        )

    # Create rental
    rental = SpotRental(
        vin=vin,
        location_name=rental_data.location_name,
        location_address=rental_data.location_address,
        check_in_date=rental_data.check_in_date,
        check_out_date=rental_data.check_out_date,
        nightly_rate=rental_data.nightly_rate,
        weekly_rate=rental_data.weekly_rate,
        monthly_rate=rental_data.monthly_rate,
        electric=rental_data.electric,
        water=rental_data.water,
        waste=rental_data.waste,
        total_cost=rental_data.total_cost,
        amenities=rental_data.amenities,
        notes=rental_data.notes,
    )

    db.add(rental)
    await db.commit()
    await db.refresh(rental)

    # Auto-create first billing entry if monthly rate is provided
    if rental_data.monthly_rate is not None and rental_data.monthly_rate > 0:
        billing_total = rental_data.monthly_rate
        if rental_data.electric:
            billing_total += rental_data.electric
        if rental_data.water:
            billing_total += rental_data.water
        if rental_data.waste:
            billing_total += rental_data.waste

        billing = SpotRentalBilling(
            spot_rental_id=rental.id,
            billing_date=rental_data.check_in_date,
            monthly_rate=rental_data.monthly_rate,
            electric=rental_data.electric,
            water=rental_data.water,
            waste=rental_data.waste,
            total=billing_total,
            notes="Initial billing entry (auto-created)"
        )
        db.add(billing)
        await db.commit()

    # Eager-load billings relationship to avoid lazy-load issues
    await db.refresh(rental, attribute_names=['billings'])

    return SpotRentalResponse.model_validate(rental)


@router.get("/{vin}/spot-rentals/{rental_id}", response_model=SpotRentalResponse)
async def get_spot_rental(
    vin: str,
    rental_id: int,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Optional[User] = Depends(require_auth),
) -> SpotRentalResponse:
    """Get a specific spot rental record."""
    result = await db.execute(
        select(SpotRental)
        .where(SpotRental.id == rental_id, SpotRental.vin == vin)
        .options(selectinload(SpotRental.billings))
    )
    rental = result.scalar_one_or_none()
    if not rental:
        raise HTTPException(status_code=404, detail="Spot rental not found")

    return SpotRentalResponse.model_validate(rental)


@router.put("/{vin}/spot-rentals/{rental_id}", response_model=SpotRentalResponse)
async def update_spot_rental(
    vin: str,
    rental_id: int,
    update_data: SpotRentalUpdate,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Optional[User] = Depends(require_auth),
) -> SpotRentalResponse:
    """Update a spot rental record."""
    # Get rental
    result = await db.execute(
        select(SpotRental)
        .where(SpotRental.id == rental_id, SpotRental.vin == vin)
        .options(selectinload(SpotRental.billings))
    )
    rental = result.scalar_one_or_none()
    if not rental:
        raise HTTPException(status_code=404, detail="Spot rental not found")

    # Update fields
    if update_data.location_name is not None:
        rental.location_name = update_data.location_name
    if update_data.location_address is not None:
        rental.location_address = update_data.location_address
    if update_data.check_in_date is not None:
        rental.check_in_date = update_data.check_in_date
    if update_data.check_out_date is not None:
        rental.check_out_date = update_data.check_out_date
    if update_data.nightly_rate is not None:
        rental.nightly_rate = update_data.nightly_rate
    if update_data.weekly_rate is not None:
        rental.weekly_rate = update_data.weekly_rate
    if update_data.monthly_rate is not None:
        rental.monthly_rate = update_data.monthly_rate
    if update_data.electric is not None:
        rental.electric = update_data.electric
    if update_data.water is not None:
        rental.water = update_data.water
    if update_data.waste is not None:
        rental.waste = update_data.waste
    if update_data.total_cost is not None:
        rental.total_cost = update_data.total_cost
    if update_data.amenities is not None:
        rental.amenities = update_data.amenities
    if update_data.notes is not None:
        rental.notes = update_data.notes

    await db.commit()
    await db.refresh(rental, attribute_names=['billings'])

    return SpotRentalResponse.model_validate(rental)


@router.delete("/{vin}/spot-rentals/{rental_id}", status_code=204)
async def delete_spot_rental(
    vin: str,
    rental_id: int,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Optional[User] = Depends(require_auth),
) -> None:
    """Delete a spot rental record."""
    # Verify rental exists
    result = await db.execute(
        select(SpotRental).where(SpotRental.id == rental_id, SpotRental.vin == vin)
    )
    rental = result.scalar_one_or_none()
    if not rental:
        raise HTTPException(status_code=404, detail="Spot rental not found")

    await db.delete(rental)
    await db.commit()

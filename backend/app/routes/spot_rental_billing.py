"""Spot rental billing routes for MyGarage API."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import SpotRental, SpotRentalBilling
from app.models.user import User
from app.schemas.spot_rental_billing import (
    SpotRentalBillingCreate,
    SpotRentalBillingListResponse,
    SpotRentalBillingResponse,
    SpotRentalBillingUpdate,
)
from app.services.auth import require_auth

router = APIRouter(prefix="/api/vehicles", tags=["spot-rental-billings"])


@router.get(
    "/{vin}/spot-rentals/{rental_id}/billings",
    response_model=SpotRentalBillingListResponse,
)
async def list_billings(
    vin: str,
    rental_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User | None = Depends(require_auth),
) -> SpotRentalBillingListResponse:
    """List all billing entries for a spot rental."""
    # Verify spot rental exists and belongs to this vehicle
    result = await db.execute(
        select(SpotRental).where(SpotRental.id == rental_id, SpotRental.vin == vin)
    )
    rental = result.scalar_one_or_none()
    if not rental:
        raise HTTPException(status_code=404, detail="Spot rental not found")

    # Get billings ordered by date descending (newest first)
    query = (
        select(SpotRentalBilling)
        .where(SpotRentalBilling.spot_rental_id == rental_id)
        .order_by(SpotRentalBilling.billing_date.desc())
    )
    result = await db.execute(query)
    billings = result.scalars().all()

    return SpotRentalBillingListResponse(
        billings=[SpotRentalBillingResponse.model_validate(b) for b in billings],
        total=len(billings),
    )


@router.post(
    "/{vin}/spot-rentals/{rental_id}/billings",
    response_model=SpotRentalBillingResponse,
    status_code=201,
)
async def create_billing(
    vin: str,
    rental_id: int,
    billing_data: SpotRentalBillingCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User | None = Depends(require_auth),
) -> SpotRentalBillingResponse:
    """Create a new billing entry for a spot rental."""
    # Verify spot rental exists and belongs to this vehicle
    result = await db.execute(
        select(SpotRental).where(SpotRental.id == rental_id, SpotRental.vin == vin)
    )
    rental = result.scalar_one_or_none()
    if not rental:
        raise HTTPException(status_code=404, detail="Spot rental not found")

    # Validate billing date is within rental period
    if billing_data.billing_date < rental.check_in_date:
        raise HTTPException(status_code=400, detail="Billing date cannot be before check-in date")

    if rental.check_out_date and billing_data.billing_date > rental.check_out_date:
        raise HTTPException(status_code=400, detail="Billing date cannot be after check-out date")

    # Create billing entry
    billing = SpotRentalBilling(
        spot_rental_id=rental_id,
        billing_date=billing_data.billing_date,
        monthly_rate=billing_data.monthly_rate,
        electric=billing_data.electric,
        water=billing_data.water,
        waste=billing_data.waste,
        total=billing_data.total,
        notes=billing_data.notes,
    )

    db.add(billing)
    await db.commit()
    await db.refresh(billing)

    return SpotRentalBillingResponse.model_validate(billing)


@router.put(
    "/{vin}/spot-rentals/{rental_id}/billings/{billing_id}",
    response_model=SpotRentalBillingResponse,
)
async def update_billing(
    vin: str,
    rental_id: int,
    billing_id: int,
    update_data: SpotRentalBillingUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User | None = Depends(require_auth),
) -> SpotRentalBillingResponse:
    """Update a billing entry."""
    # Verify billing exists and belongs to the right rental
    result = await db.execute(
        select(SpotRentalBilling)
        .join(SpotRental)
        .where(
            SpotRentalBilling.id == billing_id,
            SpotRentalBilling.spot_rental_id == rental_id,
            SpotRental.vin == vin,
        )
    )
    billing = result.scalar_one_or_none()
    if not billing:
        raise HTTPException(status_code=404, detail="Billing entry not found")

    # Update fields (only if provided)
    update_dict = update_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(billing, field, value)

    await db.commit()
    await db.refresh(billing)

    return SpotRentalBillingResponse.model_validate(billing)


@router.delete(
    "/{vin}/spot-rentals/{rental_id}/billings/{billing_id}",
    status_code=204,
)
async def delete_billing(
    vin: str,
    rental_id: int,
    billing_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: User | None = Depends(require_auth),
) -> None:
    """Delete a billing entry."""
    # Verify billing exists and belongs to the right rental
    result = await db.execute(
        select(SpotRentalBilling)
        .join(SpotRental)
        .where(
            SpotRentalBilling.id == billing_id,
            SpotRentalBilling.spot_rental_id == rental_id,
            SpotRental.vin == vin,
        )
    )
    billing = result.scalar_one_or_none()
    if not billing:
        raise HTTPException(status_code=404, detail="Billing entry not found")

    await db.delete(billing)
    await db.commit()

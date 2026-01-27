"""Warranty record API routes."""


from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Vehicle
from app.models import WarrantyRecord as WarrantyRecordModel
from app.models.user import User
from app.schemas.warranty import (
    WarrantyRecord,
    WarrantyRecordCreate,
    WarrantyRecordUpdate,
)
from app.services.auth import require_auth

router = APIRouter(prefix="/api", tags=["Warranties"])


@router.get("/vehicles/{vin}/warranties", response_model=list[WarrantyRecord])
async def get_warranties(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Get all warranty records for a vehicle."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Get warranty records
    result = await db.execute(
        select(WarrantyRecordModel)
        .where(WarrantyRecordModel.vin == vin)
        .order_by(WarrantyRecordModel.start_date.desc())
    )
    warranties = result.scalars().all()
    return warranties


@router.post(
    "/vehicles/{vin}/warranties", response_model=WarrantyRecord, status_code=201
)
async def create_warranty(
    vin: str,
    warranty: WarrantyRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Create a new warranty record."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Create warranty record
    db_warranty = WarrantyRecordModel(vin=vin, **warranty.model_dump())
    db.add(db_warranty)
    await db.commit()
    await db.refresh(db_warranty)
    return db_warranty


@router.get("/vehicles/{vin}/warranties/{warranty_id}", response_model=WarrantyRecord)
async def get_warranty(
    vin: str,
    warranty_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Get a specific warranty record."""
    result = await db.execute(
        select(WarrantyRecordModel).where(
            WarrantyRecordModel.vin == vin, WarrantyRecordModel.id == warranty_id
        )
    )
    warranty = result.scalar_one_or_none()
    if not warranty:
        raise HTTPException(status_code=404, detail="Warranty record not found")
    return warranty


@router.put("/vehicles/{vin}/warranties/{warranty_id}", response_model=WarrantyRecord)
async def update_warranty(
    vin: str,
    warranty_id: int,
    warranty_update: WarrantyRecordUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Update a warranty record."""
    result = await db.execute(
        select(WarrantyRecordModel).where(
            WarrantyRecordModel.vin == vin, WarrantyRecordModel.id == warranty_id
        )
    )
    db_warranty = result.scalar_one_or_none()
    if not db_warranty:
        raise HTTPException(status_code=404, detail="Warranty record not found")

    # Update fields
    update_data = warranty_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_warranty, field, value)

    await db.commit()
    await db.refresh(db_warranty)
    return db_warranty


@router.delete("/vehicles/{vin}/warranties/{warranty_id}", status_code=204)
async def delete_warranty(
    vin: str,
    warranty_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Delete a warranty record."""
    result = await db.execute(
        select(WarrantyRecordModel).where(
            WarrantyRecordModel.vin == vin, WarrantyRecordModel.id == warranty_id
        )
    )
    db_warranty = result.scalar_one_or_none()
    if not db_warranty:
        raise HTTPException(status_code=404, detail="Warranty record not found")

    await db.delete(db_warranty)
    await db.commit()
    return None

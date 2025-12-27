"""Tax/registration record routes for MyGarage API."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import TaxRecord, Vehicle
from app.models.user import User
from app.services.auth import require_auth
from app.schemas.tax import (
    TaxRecordCreate,
    TaxRecordListResponse,
    TaxRecordResponse,
    TaxRecordUpdate,
)

router = APIRouter(prefix="/api/vehicles", tags=["tax-records"])


@router.get("/{vin}/tax-records", response_model=TaxRecordListResponse)
async def list_tax_records(
    vin: str,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Optional[User] = Depends(require_auth),
) -> TaxRecordListResponse:
    """List all tax/registration records for a vehicle."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Get tax records ordered by date descending
    query = (
        select(TaxRecord).where(TaxRecord.vin == vin).order_by(TaxRecord.date.desc())
    )
    result = await db.execute(query)
    records = result.scalars().all()

    # Get total count
    count_result = await db.execute(
        select(func.count()).select_from(TaxRecord).where(TaxRecord.vin == vin)
    )
    total = count_result.scalar_one()

    return TaxRecordListResponse(
        records=[TaxRecordResponse.model_validate(r) for r in records],
        total=total,
    )


@router.post("/{vin}/tax-records", response_model=TaxRecordResponse, status_code=201)
async def create_tax_record(
    vin: str,
    record_data: TaxRecordCreate,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Optional[User] = Depends(require_auth),
) -> TaxRecordResponse:
    """Create a new tax/registration record."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Verify VIN matches
    if record_data.vin != vin:
        raise HTTPException(status_code=400, detail="VIN in URL and body must match")

    # Create record
    record = TaxRecord(
        vin=vin,
        date=record_data.date,
        tax_type=record_data.tax_type,
        amount=record_data.amount,
        renewal_date=record_data.renewal_date,
        notes=record_data.notes,
    )

    db.add(record)
    await db.commit()
    await db.refresh(record)

    return TaxRecordResponse.model_validate(record)


@router.get("/{vin}/tax-records/{record_id}", response_model=TaxRecordResponse)
async def get_tax_record(
    vin: str,
    record_id: int,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Optional[User] = Depends(require_auth),
) -> TaxRecordResponse:
    """Get a specific tax/registration record."""
    result = await db.execute(
        select(TaxRecord).where(TaxRecord.id == record_id, TaxRecord.vin == vin)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Tax record not found")

    return TaxRecordResponse.model_validate(record)


@router.put("/{vin}/tax-records/{record_id}", response_model=TaxRecordResponse)
async def update_tax_record(
    vin: str,
    record_id: int,
    update_data: TaxRecordUpdate,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Optional[User] = Depends(require_auth),
) -> TaxRecordResponse:
    """Update a tax/registration record."""
    # Get record
    result = await db.execute(
        select(TaxRecord).where(TaxRecord.id == record_id, TaxRecord.vin == vin)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Tax record not found")

    # Update fields
    if update_data.date is not None:
        record.date = update_data.date
    if update_data.tax_type is not None:
        record.tax_type = update_data.tax_type
    if update_data.amount is not None:
        record.amount = update_data.amount
    if update_data.renewal_date is not None:
        record.renewal_date = update_data.renewal_date
    if update_data.notes is not None:
        record.notes = update_data.notes

    await db.commit()
    await db.refresh(record)

    return TaxRecordResponse.model_validate(record)


@router.delete("/{vin}/tax-records/{record_id}", status_code=204)
async def delete_tax_record(
    vin: str,
    record_id: int,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Optional[User] = Depends(require_auth),
) -> None:
    """Delete a tax/registration record."""
    # Verify record exists
    result = await db.execute(
        select(TaxRecord).where(TaxRecord.id == record_id, TaxRecord.vin == vin)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Tax record not found")

    await db.delete(record)
    await db.commit()

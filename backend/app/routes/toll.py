"""Toll tag and transaction CRUD API endpoints."""

import logging
from fastapi import APIRouter, HTTPException, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from typing import Optional
from decimal import Decimal
import datetime as dt
import csv
import io

from app.database import get_db
from app.models.toll import TollTag, TollTransaction
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services.auth import require_auth
from app.schemas.toll import (
    TollTagCreate,
    TollTagUpdate,
    TollTagResponse,
    TollTagListResponse,
    TollTransactionCreate,
    TollTransactionUpdate,
    TollTransactionResponse,
    TollTransactionListResponse,
    TollTransactionSummary,
)

logger = logging.getLogger(__name__)


# Toll Tags Router
toll_tags_router = APIRouter(prefix="/api/vehicles/{vin}/toll-tags", tags=["Toll Tags"])


@toll_tags_router.get("", response_model=TollTagListResponse)
async def list_toll_tags(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Get all toll tags for a vehicle."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Get toll tags
    result = await db.execute(
        select(TollTag).where(TollTag.vin == vin).order_by(TollTag.created_at.desc())
    )
    toll_tags = result.scalars().all()

    return TollTagListResponse(
        toll_tags=[TollTagResponse.model_validate(tag) for tag in toll_tags],
        total=len(toll_tags),
    )


@toll_tags_router.post("", response_model=TollTagResponse, status_code=201)
async def create_toll_tag(
    vin: str,
    toll_tag: TollTagCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Create a new toll tag for a vehicle."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Create toll tag
    db_toll_tag = TollTag(
        vin=vin,
        toll_system=toll_tag.toll_system,
        tag_number=toll_tag.tag_number,
        status=toll_tag.status,
        notes=toll_tag.notes,
    )
    db.add(db_toll_tag)
    await db.commit()
    await db.refresh(db_toll_tag)

    logger.info("Created toll tag %s for vehicle %s", db_toll_tag.id, vin)
    return TollTagResponse.model_validate(db_toll_tag)


@toll_tags_router.get("/{tag_id}", response_model=TollTagResponse)
async def get_toll_tag(
    vin: str,
    tag_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Get a specific toll tag."""
    result = await db.execute(
        select(TollTag).where(TollTag.id == tag_id, TollTag.vin == vin)
    )
    toll_tag = result.scalar_one_or_none()
    if not toll_tag:
        raise HTTPException(status_code=404, detail="Toll tag not found")

    return TollTagResponse.model_validate(toll_tag)


@toll_tags_router.put("/{tag_id}", response_model=TollTagResponse)
async def update_toll_tag(
    vin: str,
    tag_id: int,
    toll_tag_update: TollTagUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Update a toll tag."""
    result = await db.execute(
        select(TollTag).where(TollTag.id == tag_id, TollTag.vin == vin)
    )
    toll_tag = result.scalar_one_or_none()
    if not toll_tag:
        raise HTTPException(status_code=404, detail="Toll tag not found")

    # Update fields
    update_data = toll_tag_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(toll_tag, field, value)

    await db.commit()
    await db.refresh(toll_tag)

    logger.info("Updated toll tag %s for vehicle %s", tag_id, vin)
    return TollTagResponse.model_validate(toll_tag)


@toll_tags_router.delete("/{tag_id}", status_code=204)
async def delete_toll_tag(
    vin: str,
    tag_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Delete a toll tag."""
    result = await db.execute(
        select(TollTag).where(TollTag.id == tag_id, TollTag.vin == vin)
    )
    toll_tag = result.scalar_one_or_none()
    if not toll_tag:
        raise HTTPException(status_code=404, detail="Toll tag not found")

    await db.execute(delete(TollTag).where(TollTag.id == tag_id))
    await db.commit()

    logger.info("Deleted toll tag %s for vehicle %s", tag_id, vin)
    return Response(status_code=204)


# Toll Transactions Router
toll_transactions_router = APIRouter(
    prefix="/api/vehicles/{vin}/toll-transactions", tags=["Toll Transactions"]
)


@toll_transactions_router.get("", response_model=TollTransactionListResponse)
async def list_toll_transactions(
    vin: str,
    start_date: Optional[dt.date] = None,
    end_date: Optional[dt.date] = None,
    toll_tag_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Get all toll transactions for a vehicle with optional filtering."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Build query
    query = select(TollTransaction).where(TollTransaction.vin == vin)

    if start_date:
        query = query.where(TollTransaction.date >= start_date)
    if end_date:
        query = query.where(TollTransaction.date <= end_date)
    if toll_tag_id:
        query = query.where(TollTransaction.toll_tag_id == toll_tag_id)

    query = query.order_by(TollTransaction.date.desc())

    # Execute query
    result = await db.execute(query)
    transactions = result.scalars().all()

    return TollTransactionListResponse(
        transactions=[
            TollTransactionResponse.model_validate(txn) for txn in transactions
        ],
        total=len(transactions),
    )


@toll_transactions_router.post(
    "", response_model=TollTransactionResponse, status_code=201
)
async def create_toll_transaction(
    vin: str,
    transaction: TollTransactionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Create a new toll transaction for a vehicle."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Verify toll tag exists if provided
    if transaction.toll_tag_id:
        result = await db.execute(
            select(TollTag).where(
                TollTag.id == transaction.toll_tag_id, TollTag.vin == vin
            )
        )
        toll_tag = result.scalar_one_or_none()
        if not toll_tag:
            raise HTTPException(status_code=404, detail="Toll tag not found")

    # Create transaction
    db_transaction = TollTransaction(
        vin=vin,
        toll_tag_id=transaction.toll_tag_id,
        date=transaction.transaction_date,
        amount=transaction.amount,
        location=transaction.location,
        notes=transaction.notes,
    )
    db.add(db_transaction)
    await db.commit()
    await db.refresh(db_transaction)

    logger.info("Created toll transaction %s for vehicle %s", db_transaction.id, vin)
    return TollTransactionResponse.model_validate(db_transaction)


@toll_transactions_router.get(
    "/{transaction_id}", response_model=TollTransactionResponse
)
async def get_toll_transaction(
    vin: str,
    transaction_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Get a specific toll transaction."""
    result = await db.execute(
        select(TollTransaction).where(
            TollTransaction.id == transaction_id, TollTransaction.vin == vin
        )
    )
    transaction = result.scalar_one_or_none()
    if not transaction:
        raise HTTPException(status_code=404, detail="Toll transaction not found")

    return TollTransactionResponse.model_validate(transaction)


@toll_transactions_router.put(
    "/{transaction_id}", response_model=TollTransactionResponse
)
async def update_toll_transaction(
    vin: str,
    transaction_id: int,
    transaction_update: TollTransactionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Update a toll transaction."""
    result = await db.execute(
        select(TollTransaction).where(
            TollTransaction.id == transaction_id, TollTransaction.vin == vin
        )
    )
    transaction = result.scalar_one_or_none()
    if not transaction:
        raise HTTPException(status_code=404, detail="Toll transaction not found")

    # Verify toll tag exists if provided
    if transaction_update.toll_tag_id:
        result = await db.execute(
            select(TollTag).where(
                TollTag.id == transaction_update.toll_tag_id, TollTag.vin == vin
            )
        )
        toll_tag = result.scalar_one_or_none()
        if not toll_tag:
            raise HTTPException(status_code=404, detail="Toll tag not found")

    # Update fields
    update_data = transaction_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(transaction, field, value)

    await db.commit()
    await db.refresh(transaction)

    logger.info("Updated toll transaction %s for vehicle %s", transaction_id, vin)
    return TollTransactionResponse.model_validate(transaction)


@toll_transactions_router.delete("/{transaction_id}", status_code=204)
async def delete_toll_transaction(
    vin: str,
    transaction_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Delete a toll transaction."""
    result = await db.execute(
        select(TollTransaction).where(
            TollTransaction.id == transaction_id, TollTransaction.vin == vin
        )
    )
    transaction = result.scalar_one_or_none()
    if not transaction:
        raise HTTPException(status_code=404, detail="Toll transaction not found")

    await db.execute(
        delete(TollTransaction).where(TollTransaction.id == transaction_id)
    )
    await db.commit()

    logger.info("Deleted toll transaction %s for vehicle %s", transaction_id, vin)
    return Response(status_code=204)


@toll_transactions_router.get(
    "/summary/statistics", response_model=TollTransactionSummary
)
async def get_toll_transaction_summary(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Get toll transaction summary and monthly statistics."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Get total count and amount
    result = await db.execute(
        select(func.count(TollTransaction.id), func.sum(TollTransaction.amount)).where(
            TollTransaction.vin == vin
        )
    )
    total_count, total_amount = result.one()

    # Get monthly totals
    month_col = func.strftime("%Y-%m", TollTransaction.date).label("month")
    result = await db.execute(
        select(
            month_col,
            func.count(TollTransaction.id).label("count"),
            func.sum(TollTransaction.amount).label("amount"),
        )
        .where(TollTransaction.vin == vin)
        .group_by(month_col)
        .order_by(month_col.desc())
    )
    monthly_data = result.all()

    monthly_totals = [
        {
            "month": row.month,
            "count": row.count,
            "amount": float(row.amount) if row.amount else 0.0,
        }
        for row in monthly_data
    ]

    return TollTransactionSummary(
        total_transactions=total_count or 0,
        total_amount=total_amount or Decimal("0.00"),
        monthly_totals=monthly_totals,
    )


@toll_transactions_router.get("/export/csv")
async def export_toll_transactions_csv(
    vin: str,
    start_date: Optional[dt.date] = None,
    end_date: Optional[dt.date] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Export toll transactions as CSV."""
    # Verify vehicle exists
    result = await db.execute(select(Vehicle).where(Vehicle.vin == vin))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Build query
    query = (
        select(TollTransaction, TollTag)
        .outerjoin(TollTag, TollTransaction.toll_tag_id == TollTag.id)
        .where(TollTransaction.vin == vin)
    )

    if start_date:
        query = query.where(TollTransaction.date >= start_date)
    if end_date:
        query = query.where(TollTransaction.date <= end_date)

    query = query.order_by(TollTransaction.date.desc())

    # Execute query
    result = await db.execute(query)
    rows = result.all()

    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow(
        [
            "Date",
            "Amount",
            "Location",
            "Toll System",
            "Tag Number",
            "Notes",
            "Vehicle",
            "VIN",
        ]
    )

    # Data rows
    for transaction, toll_tag in rows:
        writer.writerow(
            [
                transaction.date.isoformat(),
                f"${float(transaction.amount):.2f}",
                transaction.location,
                toll_tag.toll_system if toll_tag else "",
                toll_tag.tag_number if toll_tag else "",
                transaction.notes or "",
                f"{vehicle.year or ''} {vehicle.make or ''} {vehicle.model or ''}".strip()
                or vehicle.nickname,
                vehicle.vin,
            ]
        )

    # Return CSV response
    csv_content = output.getvalue()
    output.close()

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=toll_transactions_{vin}_{dt.date.today().isoformat()}.csv"
        },
    )

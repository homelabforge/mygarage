"""Toll tag and transaction CRUD API endpoints."""

import csv
import datetime as dt
import io
import logging

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.toll import TollTag, TollTransaction
from app.models.user import User
from app.schemas.toll import (
    TollTagCreate,
    TollTagListResponse,
    TollTagResponse,
    TollTagUpdate,
    TollTransactionCreate,
    TollTransactionListResponse,
    TollTransactionResponse,
    TollTransactionSummary,
    TollTransactionUpdate,
)
from app.services.auth import get_vehicle_or_403, require_auth
from app.services.toll_service import TollService

logger = logging.getLogger(__name__)


# Toll Tags Router
toll_tags_router = APIRouter(prefix="/api/vehicles/{vin}/toll-tags", tags=["Toll Tags"])


@toll_tags_router.get("", response_model=TollTagListResponse)
async def list_toll_tags(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> TollTagListResponse:
    """Get all toll tags for a vehicle."""
    service = TollService(db)
    return await service.list_tags(vin, current_user)


@toll_tags_router.post("", response_model=TollTagResponse, status_code=201)
async def create_toll_tag(
    vin: str,
    toll_tag: TollTagCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> TollTagResponse:
    """Create a new toll tag for a vehicle."""
    service = TollService(db)
    return await service.create_tag(vin, toll_tag, current_user)


@toll_tags_router.get("/{tag_id}", response_model=TollTagResponse)
async def get_toll_tag(
    vin: str,
    tag_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> TollTagResponse:
    """Get a specific toll tag."""
    service = TollService(db)
    return await service.get_tag(vin, tag_id, current_user)


@toll_tags_router.put("/{tag_id}", response_model=TollTagResponse)
async def update_toll_tag(
    vin: str,
    tag_id: int,
    toll_tag_update: TollTagUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> TollTagResponse:
    """Update a toll tag."""
    service = TollService(db)
    return await service.update_tag(vin, tag_id, toll_tag_update, current_user)


@toll_tags_router.delete("/{tag_id}", status_code=204)
async def delete_toll_tag(
    vin: str,
    tag_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> None:
    """Delete a toll tag."""
    service = TollService(db)
    await service.delete_tag(vin, tag_id, current_user)


# Toll Transactions Router
toll_transactions_router = APIRouter(
    prefix="/api/vehicles/{vin}/toll-transactions", tags=["Toll Transactions"]
)


@toll_transactions_router.get("", response_model=TollTransactionListResponse)
async def list_toll_transactions(
    vin: str,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    toll_tag_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> TollTransactionListResponse:
    """Get all toll transactions for a vehicle with optional filtering."""
    service = TollService(db)
    return await service.list_transactions(vin, current_user, start_date, end_date, toll_tag_id)


@toll_transactions_router.post("", response_model=TollTransactionResponse, status_code=201)
async def create_toll_transaction(
    vin: str,
    transaction: TollTransactionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> TollTransactionResponse:
    """Create a new toll transaction for a vehicle."""
    service = TollService(db)
    return await service.create_transaction(vin, transaction, current_user)


@toll_transactions_router.get("/{transaction_id}", response_model=TollTransactionResponse)
async def get_toll_transaction(
    vin: str,
    transaction_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> TollTransactionResponse:
    """Get a specific toll transaction."""
    service = TollService(db)
    return await service.get_transaction(vin, transaction_id, current_user)


@toll_transactions_router.put("/{transaction_id}", response_model=TollTransactionResponse)
async def update_toll_transaction(
    vin: str,
    transaction_id: int,
    transaction_update: TollTransactionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> TollTransactionResponse:
    """Update a toll transaction."""
    service = TollService(db)
    return await service.update_transaction(vin, transaction_id, transaction_update, current_user)


@toll_transactions_router.delete("/{transaction_id}", status_code=204)
async def delete_toll_transaction(
    vin: str,
    transaction_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> None:
    """Delete a toll transaction."""
    service = TollService(db)
    await service.delete_transaction(vin, transaction_id, current_user)


@toll_transactions_router.get("/summary/statistics", response_model=TollTransactionSummary)
async def get_toll_transaction_summary(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> TollTransactionSummary:
    """Get toll transaction summary and monthly statistics."""
    service = TollService(db)
    return await service.get_summary(vin, current_user)


@toll_transactions_router.get("/export/csv")
async def export_toll_transactions_csv(
    vin: str,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Export toll transactions as CSV."""
    vehicle = await get_vehicle_or_403(vin, current_user, db)

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

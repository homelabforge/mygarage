"""Global parts & supplies catalog routes.

Authorization model: supplies are a shared household catalog, exactly like
``address_book``. Every route is authenticated (``require_auth``). There is no
per-vehicle authorization here because a supply is NOT a vehicle-owned child
record — it is a household-level item with an optional, non-authoritative ``vin``
pin (see ``Supply.created_by_user_id`` "provenance only, not an access wall").
Routes therefore key on the supply ``id``; the ``vin`` query param is a display
filter, never an access boundary.

Vehicle-scoped access control lives where it belongs: the per-vehicle
supply-usages read route is vin-scoped and gates with ``get_vehicle_or_403``,
and job consumption is written through the already write-gated service-visit
flow. This module deliberately has no vehicle gate because it guards no
vehicle-owned data. The same applies to the purchase-receipt attachment
routes below: receipts belong to the shared catalog, not to a vehicle.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.attachment import Attachment
from app.models.supply import SupplyPurchase
from app.models.user import User
from app.schemas.supply import (
    SupplyAdjustmentCreate,
    SupplyCreate,
    SupplyHistoryResponse,
    SupplyListResponse,
    SupplyPurchaseCreate,
    SupplyPurchaseResponse,
    SupplyResponse,
    SupplyUpdate,
    SupplyUsageResponse,
    VehicleSupplyUsagesResponse,
)
from app.services.auth import require_auth
from app.services.file_upload_service import ATTACHMENT_UPLOAD_CONFIG, FileUploadService
from app.services.supply_service import SupplyService

router = APIRouter(prefix="/api/supplies", tags=["supplies"])


async def _get_purchase_or_404(
    db: AsyncSession, supply_id: int, purchase_id: int
) -> SupplyPurchase:
    """Resolve a purchase, 404ing if missing OR if it belongs to a different supply."""
    purchase = (
        await db.execute(
            select(SupplyPurchase)
            .where(SupplyPurchase.id == purchase_id)
            .where(SupplyPurchase.supply_id == supply_id)
        )
    ).scalar_one_or_none()
    if not purchase:
        raise HTTPException(status_code=404, detail=f"Purchase {purchase_id} not found")
    return purchase


@router.get("", response_model=SupplyListResponse)
async def list_supplies(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(require_auth)],
    include_archived: bool = Query(False),
    vin: str | None = Query(None),
) -> SupplyListResponse:
    """List catalog supplies with ledger-derived balances."""
    supplies, total = await SupplyService(db).list_supplies(
        current_user, include_archived=include_archived, vin=vin
    )
    return SupplyListResponse(supplies=supplies, total=total)


@router.post("", response_model=SupplyResponse, status_code=status.HTTP_201_CREATED)
async def create_supply(
    data: SupplyCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(require_auth)],
) -> SupplyResponse:
    """Create a catalog supply."""
    return await SupplyService(db).create_supply(data, current_user)


@router.get("/{supply_id}", response_model=SupplyResponse)
async def get_supply(
    supply_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(require_auth)],
) -> SupplyResponse:
    """Get a single catalog supply with its current balance."""
    svc = SupplyService(db)
    supply = await svc.get_supply(supply_id)
    on_hand, avg = (await svc._compute_balances([supply_id]))[supply_id]
    return svc._to_supply_response(supply, on_hand, avg)


@router.patch("/{supply_id}", response_model=SupplyResponse)
async def update_supply(
    supply_id: int,
    data: SupplyUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(require_auth)],
) -> SupplyResponse:
    """Patch a catalog supply. unit_type is intentionally immutable."""
    return await SupplyService(db).update_supply(supply_id, data, current_user)


@router.delete("/{supply_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_supply(
    supply_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(require_auth)],
) -> Response:
    """Delete a catalog supply — hard-delete if unused, soft-archive if it has ledger history."""
    await SupplyService(db).delete_supply(supply_id, current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{supply_id}/purchases",
    response_model=SupplyPurchaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_purchase(
    supply_id: int,
    data: SupplyPurchaseCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(require_auth)],
) -> SupplyPurchaseResponse:
    """Record a stock-in purchase for a supply."""
    purchase = await SupplyService(db).add_purchase(supply_id, data, current_user)
    return SupplyPurchaseResponse.model_validate(purchase)


@router.delete("/{supply_id}/purchases/{purchase_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_purchase(
    supply_id: int,
    purchase_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(require_auth)],
) -> Response:
    """Delete a purchase (and its receipt, if any) from the ledger."""
    await SupplyService(db).delete_purchase(supply_id, purchase_id, current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{supply_id}/adjustments",
    response_model=SupplyUsageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_adjustment(
    supply_id: int,
    data: SupplyAdjustmentCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(require_auth)],
) -> SupplyUsageResponse:
    """Record a standalone stock-out (not tied to a service line item)."""
    svc = SupplyService(db)
    usage = await svc.add_adjustment(supply_id, data, current_user)
    await db.refresh(usage, attribute_names=["supply"])
    return svc.to_usage_response(usage)


@router.delete("/{supply_id}/adjustments/{usage_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_adjustment(
    supply_id: int,
    usage_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(require_auth)],
) -> Response:
    """Delete a standalone adjustment. Job-linked usages must be edited via the visit."""
    await SupplyService(db).delete_adjustment(supply_id, usage_id, current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{supply_id}/history", response_model=SupplyHistoryResponse)
async def supply_history(
    supply_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(require_auth)],
) -> SupplyHistoryResponse:
    """Full chronological purchase/usage ledger for a supply, with running balance."""
    return await SupplyService(db).get_supply_history(supply_id, current_user)


# ---- purchase receipts -------------------------------------------------------


@router.post(
    "/{supply_id}/purchases/{purchase_id}/receipt",
    status_code=status.HTTP_201_CREATED,
)
async def upload_receipt(
    supply_id: int,
    purchase_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(require_auth)],
    file: UploadFile = File(...),
) -> dict:
    """Upload (or REPLACE) the single receipt for a purchase — one-per-purchase (R1-H4)."""
    await _get_purchase_or_404(db, supply_id, purchase_id)
    svc = SupplyService(db)
    old_files = await svc._purge_receipt(purchase_id)  # atomic replace: drop any existing row
    # Flush the DELETE now, before the new row is even created. SQLAlchemy's unit-of-work
    # otherwise emits pending INSERTs before pending DELETEs within a single flush, which
    # would land the new row while the old one (same purchase_id) still exists and trip the
    # partial unique index (uq_supply_purchase_receipt) on a plain same-request replace —
    # not just a genuine cross-session race. Still inside the same transaction, so a later
    # rollback undoes this delete too.
    await db.flush()
    upload = await FileUploadService.upload_file(
        file, ATTACHMENT_UPLOAD_CONFIG, subdirectory=f"supply_purchase/{purchase_id}"
    )
    attachment = Attachment(
        record_type="supply_purchase",
        record_id=purchase_id,
        file_path=str(upload.file_path),
        file_type=upload.content_type,
        file_size=upload.file_size,
    )
    db.add(attachment)
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent upload won the one-per-purchase race (partial unique index, R1-H4).
        await db.rollback()
        SupplyService._unlink_files([str(upload.file_path)])
        raise HTTPException(status_code=409, detail="A receipt for this purchase already exists")
    except Exception:
        # Any other DB failure after the file landed — don't orphan the new file.
        await db.rollback()
        SupplyService._unlink_files([str(upload.file_path)])
        raise
    svc._unlink_files(old_files)  # remove replaced file(s) only after a successful commit
    await db.refresh(attachment)
    return {"id": attachment.id, "file_type": attachment.file_type}


@router.get("/{supply_id}/purchases/{purchase_id}/receipt")
async def download_receipt(
    supply_id: int,
    purchase_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(require_auth)],
) -> FileResponse:
    """Download the receipt file for a purchase."""
    await _get_purchase_or_404(db, supply_id, purchase_id)
    attachment = (
        await db.execute(
            select(Attachment)
            .where(Attachment.record_type == "supply_purchase")
            .where(Attachment.record_id == purchase_id)
        )
    ).scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=404, detail="No receipt for this purchase")
    return FileResponse(
        attachment.file_path, media_type=attachment.file_type or "application/octet-stream"
    )


@router.delete(
    "/{supply_id}/purchases/{purchase_id}/receipt",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_receipt(
    supply_id: int,
    purchase_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(require_auth)],
) -> Response:
    """Delete the receipt for a purchase, if any."""
    await _get_purchase_or_404(db, supply_id, purchase_id)
    svc = SupplyService(db)
    paths = await svc._purge_receipt(purchase_id)
    if not paths:
        raise HTTPException(status_code=404, detail="No receipt for this purchase")
    await db.commit()
    svc._unlink_files(paths)  # unlink files only after the row deletion commits (R1-H4)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- per-vehicle usage read (vin-scoped, unlike the catalog routes above) ---

vehicle_supplies_router = APIRouter(prefix="/api/vehicles", tags=["vehicle-supplies"])


@vehicle_supplies_router.get("/{vin}/supply-usages", response_model=VehicleSupplyUsagesResponse)
async def list_vehicle_supply_usages(
    vin: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(require_auth)],
) -> VehicleSupplyUsagesResponse:
    """All supply usages consumed on this vehicle's service visits (read-gated)."""
    return await SupplyService(db).list_vehicle_supply_usages(vin, current_user)

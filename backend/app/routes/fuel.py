"""Fuel Record CRUD API endpoints with MPG calculation."""

import logging
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.drive_session import DriveSession
from app.models.user import User
from app.schemas.fuel import (
    FuelReceiptParseResponse,
    FuelRecordCreate,
    FuelRecordListResponse,
    FuelRecordResponse,
    FuelRecordUpdate,
    ObcSuggestionResponse,
)
from app.services.auth import get_vehicle_or_403, require_auth
from app.services.fuel_service import FuelRecordService, build_fuel_response
from app.services.receipt_parse_service import parse_receipt_draft

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vehicles/{vin}/fuel", tags=["Fuel Records"])
limiter = Limiter(key_func=get_remote_address)
# Receipt images go through OCR + an LLM call — cap like other uploads.
MAX_RECEIPT_UPLOAD_BYTES = settings.max_upload_size_bytes
MAX_RECEIPT_TEXT_CHARS = 16_000


@router.get("", response_model=FuelRecordListResponse)
async def list_fuel_records(
    vin: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    include_hauling: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get all fuel records for a vehicle with MPG calculations.

    **Path Parameters:**
    - **vin**: Vehicle VIN

    **Query Parameters:**
    - **skip**: Number of records to skip (pagination)
    - **limit**: Maximum number of records to return
    - **include_hauling**: Include towing/hauling records in MPG calculation (default: False)

    **Returns:**
    - List of fuel records with MPG and average MPG

    **Security:**
    - Users can only access fuel records for their own vehicles
    - Admin users can access all fuel records
    """
    service = FuelRecordService(db)
    responses, total, avg_value, avg_l_per_hr, avg_cost_per_hr = await service.list_fuel_records(
        vin, current_user, skip, limit, include_hauling
    )

    return FuelRecordListResponse(
        records=responses,
        total=total,
        average_l_per_100km=avg_value,
        average_l_per_hr=avg_l_per_hr,
        average_cost_per_hr=avg_cost_per_hr,
    )


# Maximum window between a DriveSession's `ended_at` and the fuel record's
# `filled_at` for OBC auto-suggest. Keeps suggestions tightly coupled to the
# drive that immediately preceded the fill-up.
OBC_SUGGESTION_WINDOW = timedelta(hours=24)


# IMPORTANT: must be declared BEFORE `/{record_id}` so FastAPI's declaration-
# order routing doesn't try to parse path segments as an int record_id.
@router.post("/parse-receipt", response_model=FuelReceiptParseResponse)
@limiter.limit(settings.rate_limit_uploads)
async def parse_fuel_receipt(
    request: Request,
    vin: str,
    text: str | None = Form(None),
    file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Parse a fuel receipt into a draft FuelRecord payload (does not persist).

    Requires ``llm_receipt_parse_enabled``. Accepts multipart image/file and/or
    a ``text`` form field. Returns draft fields only — never writes FuelRecord.
    """
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db, require_write=True)

    if text is not None and len(text) > MAX_RECEIPT_TEXT_CHARS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Receipt text exceeds maximum of {MAX_RECEIPT_TEXT_CHARS} characters",
        )

    file_bytes: bytes | None = None
    filename: str | None = None
    content_type: str | None = None
    if file is not None and file.filename:
        # Size comes from the spooled temp file BEFORE the read, matching
        # file_upload_service.py and insurance.py. Checking len() after
        # `await file.read()` still materialises the whole upload as a bytes
        # object first, so the 413 was cosmetic on a single-worker process.
        # This does not avoid the multipart spool itself, only the RAM copy.
        file.file.seek(0, 2)
        file_size = file.file.tell()
        file.file.seek(0)
        if file_size > MAX_RECEIPT_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"Receipt file exceeds maximum of {MAX_RECEIPT_UPLOAD_BYTES // (1024 * 1024)}MB"
                ),
            )
        file_bytes = await file.read()
        filename = file.filename
        content_type = file.content_type

    result = await parse_receipt_draft(
        db,
        text=text,
        file_bytes=file_bytes,
        filename=filename,
        content_type=content_type,
    )
    return FuelReceiptParseResponse.model_validate(result)


@router.get("/obc-suggestion", response_model=ObcSuggestionResponse)
async def obc_suggestion(
    vin: str,
    at: datetime = Query(
        ...,
        description=(
            "Fill-up timestamp (naive local). Returns the most recent "
            "DriveSession that ended on or before this time within a 24-hour window."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
) -> ObcSuggestionResponse:
    """Return OBC values from the DriveSession that immediately preceded a fill-up.

    Used by the fuel form's "Auto-fill from last drive" button. Always
    returns 404 when there's no usable session — the frontend then hides
    the button entirely.
    """
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db)

    cutoff = at - OBC_SUGGESTION_WINDOW
    result = await db.execute(
        select(DriveSession)
        .where(DriveSession.vin == vin)
        .where(DriveSession.ended_at.isnot(None))
        .where(DriveSession.ended_at <= at)
        .where(DriveSession.ended_at >= cutoff)
        .where(DriveSession.distance_km.isnot(None))
        .order_by(DriveSession.ended_at.desc())
        .limit(1)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(
            status_code=404,
            detail="No matching drive session within the 24-hour window",
        )

    # Compute L/100km from session aggregates when fuel_used_estimate is set.
    obc_l_per_100km: Decimal | None = None
    if (
        session.fuel_used_estimate is not None
        and session.distance_km is not None
        and session.distance_km > 0
    ):
        try:
            obc_l_per_100km = (
                Decimal(str(session.fuel_used_estimate))
                / Decimal(str(session.distance_km))
                * Decimal("100")
            ).quantize(Decimal("0.01"))
        except Exception:
            obc_l_per_100km = None

    avg_speed = (
        Decimal(str(session.avg_speed)).quantize(Decimal("0.1"))
        if session.avg_speed is not None
        else None
    )
    distance = (
        Decimal(str(session.distance_km)).quantize(Decimal("0.01"))
        if session.distance_km is not None
        else None
    )

    return ObcSuggestionResponse(
        session_id=session.id,
        ended_at=session.ended_at,
        distance_km=distance,
        obc_l_per_100km=obc_l_per_100km,
        obc_avg_speed_kmh=avg_speed,
        obc_trip_duration_s=session.duration_seconds,
    )


@router.get("/{record_id}", response_model=FuelRecordResponse)
async def get_fuel_record(
    vin: str,
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get a specific fuel record with MPG calculation.

    **Path Parameters:**
    - **vin**: Vehicle VIN
    - **record_id**: Fuel record ID

    **Returns:**
    - Fuel record details with MPG

    **Raises:**
    - **404**: Record not found
    - **403**: Not authorized

    **Security:**
    - Users can only access fuel records for their own vehicles
    - Admin users can access all fuel records
    """
    service = FuelRecordService(db)
    record, mpg, l_per_hr = await service.get_fuel_record(vin, record_id, current_user)

    return await build_fuel_response(db, record, mpg, l_per_hr)


@router.post("", response_model=FuelRecordResponse, status_code=201)
async def create_fuel_record(
    vin: str,
    record_data: FuelRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Create a new fuel record with MPG calculation.

    **Security:**
    - Users can only create fuel records for their own vehicles
    - Admin users can create fuel records for all vehicles
    """
    service = FuelRecordService(db)
    record, mpg, l_per_hr = await service.create_fuel_record(vin, record_data, current_user)

    return await build_fuel_response(db, record, mpg, l_per_hr)


@router.put("/{record_id}", response_model=FuelRecordResponse)
async def update_fuel_record(
    vin: str,
    record_id: int,
    record_data: FuelRecordUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Update an existing fuel record.

    **Security:**
    - Users can only update fuel records for their own vehicles
    - Admin users can update all fuel records
    """
    service = FuelRecordService(db)
    record, mpg, l_per_hr = await service.update_fuel_record(
        vin, record_id, record_data, current_user
    )

    return await build_fuel_response(db, record, mpg, l_per_hr)


@router.delete("/{record_id}", status_code=204)
async def delete_fuel_record(
    vin: str,
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Delete a fuel record.

    **Security:**
    - Users can only delete fuel records for their own vehicles
    - Admin users can delete all fuel records
    """
    service = FuelRecordService(db)
    await service.delete_fuel_record(vin, record_id, current_user)

    return None

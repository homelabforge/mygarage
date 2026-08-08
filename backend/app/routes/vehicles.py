"""Vehicle CRUD API endpoints."""

import logging
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    DEFRecord,
    FuelRecord,
    Reminder,
    ServiceVisit,
)
from app.models.user import User
from app.models.vehicle import TrailerDetails, Vehicle
from app.schemas.vehicle import (
    TrailerDetailsCreate,
    TrailerDetailsResponse,
    TrailerDetailsUpdate,
    VehicleArchiveRequest,
    VehicleCreate,
    VehicleDetailStats,
    VehicleListResponse,
    VehicleResponse,
    VehicleUpdate,
)
from app.services.auth import (
    get_vehicle_for_owner_or_403,
    get_vehicle_or_403,
    require_auth,
)
from app.services.fuel_service import calculate_average_hours_economy
from app.services.hours_service import latest_engine_hours_and_date
from app.services.odometer_service import latest_odometer_km_and_date
from app.services.reminder_service import is_reminder_overdue
from app.services.service_visit_service import service_visit_cost_load_options
from app.services.vehicle_service import VehicleService
from app.utils.datetime_utils import utc_now
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/vehicles", tags=["Vehicles"])

_NON_MOTORIZED = frozenset({"Trailer", "FifthWheel", "TravelTrailer"})


async def _validate_tow_vehicle_vin(
    db: AsyncSession,
    current_user: User,
    tow_vin: str | None,
) -> str | None:
    """Ensure tow VIN is an accessible motorized vehicle when provided."""
    if not tow_vin:
        return None
    tow_vin = tow_vin.upper().strip()
    tow_vehicle = await get_vehicle_or_403(tow_vin, current_user, db)
    if tow_vehicle.vehicle_type in _NON_MOTORIZED:
        raise HTTPException(
            status_code=400,
            detail="Tow vehicle must be a motorized vehicle (not a trailer)",
        )
    return tow_vin


@router.get("", response_model=VehicleListResponse)
async def list_vehicles(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get list of all vehicles.

    **Query Parameters:**
    - **skip**: Number of records to skip (pagination)
    - **limit**: Maximum number of records to return

    **Returns:**
    - List of vehicles with total count

    **Security:**
    - Users see only their own vehicles
    - Admin users see all vehicles
    """
    service = VehicleService(db)
    vehicles, total = await service.list_vehicles(current_user, skip, limit)

    return VehicleListResponse(
        vehicles=[VehicleResponse.model_validate(v) for v in vehicles], total=total
    )


@router.get("/{vin}", response_model=VehicleResponse)
async def get_vehicle(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Get a specific vehicle by VIN.

    **Args:**
    - **vin**: 17-character Vehicle Identification Number

    **Returns:**
    - Vehicle details

    **Raises:**
    - **404**: Vehicle not found
    - **403**: Not authorized to access this vehicle

    **Security:**
    - Users can only access their own vehicles
    - Admin users can access all vehicles
    """
    service = VehicleService(db)
    vehicle = await service.get_vehicle(vin, current_user)

    return VehicleResponse.model_validate(vehicle)


async def _vehicle_detail_stats(db: AsyncSession, vin: str) -> VehicleDetailStats:
    """Aggregate the Vehicle Detail hero/key-facts stats for one vehicle.

    Reuses the per-vehicle overdue/upcoming logic (dashboard.calculate_vehicle_stats)
    and the YTD running-cost set (dashboard.calculate_fleet_health): service +
    fuel + DEF dated year_start..today. All filters are Date-vs-Python-date
    ranges (dialect-portable, no EXTRACT/strftime). Costs are Decimal, never
    float. latest_odometer_km stays raw canonical km (converted at the API
    boundary on the client).
    """
    today = date.today()
    year = today.year
    year_start = date(year, 1, 1)

    # Usage tracking dimension (drives the odometer/hours relabel). One small fetch;
    # the caller has already gated the vin's existence.
    usage_row = (
        await db.execute(
            select(
                Vehicle.usage_unit, Vehicle.current_hours, Vehicle.secondary_usage_enabled
            ).where(Vehicle.vin == vin)
        )
    ).first()
    usage_unit = usage_row[0] if usage_row else "distance"
    current_hours = usage_row[1] if usage_row else None
    secondary_usage_enabled = usage_row[2] if usage_row else False

    # Canonical latest engine-hours reading (§1 helper) — NEVER vehicle.current_hours
    # (R2-H1). Null for a pure-distance vehicle (no hours_records rows).
    latest_hours, _latest_hours_date = await latest_engine_hours_and_date(db, vin)
    average_l_per_hr, average_cost_per_hr = await calculate_average_hours_economy(db, vin)

    # Latest odometer reading (km) + its date — ONE deterministic fetch via the
    # SHARED helper (date DESC, id DESC), the SAME selection the dashboard's
    # calculate_vehicle_stats now uses (R2-B1/B2), so the two routes agree on a
    # same-date-reading vehicle. The model has no VIN/date uniqueness
    # (app/models/odometer.py:21), hence the id.desc() tie-break inside the helper.
    # current_odometer_km for the mileage-reminder evaluation is derived from THIS
    # SAME returned row (reused, not a second query) so the displayed reading and
    # the mileage-eval reading can never disagree.
    latest_odometer_km, latest_odometer_date = await latest_odometer_km_and_date(db, vin)
    current_odometer_km = latest_odometer_km  # one determination, reused below

    # Last service / last fill-up dates (id.desc() secondary sort = dialect-stable).
    last_service_date = await db.scalar(
        select(ServiceVisit.date)
        .where(ServiceVisit.vin == vin)
        .order_by(ServiceVisit.date.desc(), ServiceVisit.id.desc())
        .limit(1)
    )
    last_fillup_date = await db.scalar(
        select(FuelRecord.date)
        .where(FuelRecord.vin == vin)
        .order_by(FuelRecord.date.desc(), FuelRecord.id.desc())
        .limit(1)
    )

    # Overdue / upcoming — shared hours-aware predicate (is_reminder_overdue,
    # Phase 6b), identical to dashboard.calculate_vehicle_stats and
    # family_dashboard_service (G8). current_odometer_km and latest_hours are
    # both reused from the single fetches above (NO extra query), so a pure
    # `hours` reminder agrees across dashboard, family dashboard, calendar,
    # and this detail-stats endpoint.
    pending = (
        (
            await db.execute(
                select(Reminder).where(Reminder.vin == vin, Reminder.status == "pending")
            )
        )
        .scalars()
        .all()
    )
    overdue_count = 0
    upcoming_count = 0
    for reminder in pending:
        if is_reminder_overdue(reminder, current_odometer_km, latest_hours, today):
            overdue_count += 1
        else:
            upcoming_count += 1

    # Spent this year — service (property) + fuel + DEF, dated year_start..today.
    service_visits = (
        (
            await db.execute(
                select(ServiceVisit)
                .options(*service_visit_cost_load_options())
                .where(
                    ServiceVisit.vin == vin,
                    ServiceVisit.date >= year_start,
                    ServiceVisit.date <= today,
                )
            )
        )
        .scalars()
        .all()
    )
    service_spent = sum((v.calculated_total_cost for v in service_visits), Decimal("0.00"))

    fuel_costs = (
        (
            await db.execute(
                select(FuelRecord.cost).where(
                    FuelRecord.vin == vin,
                    FuelRecord.cost.isnot(None),
                    FuelRecord.date >= year_start,
                    FuelRecord.date <= today,
                )
            )
        )
        .scalars()
        .all()
    )
    fuel_spent = sum((c for c in fuel_costs if c is not None), Decimal("0.00"))

    def_costs = (
        (
            await db.execute(
                select(DEFRecord.cost).where(
                    DEFRecord.vin == vin,
                    DEFRecord.cost.isnot(None),
                    DEFRecord.date >= year_start,
                    DEFRecord.date <= today,
                )
            )
        )
        .scalars()
        .all()
    )
    def_spent = sum((c for c in def_costs if c is not None), Decimal("0.00"))

    return VehicleDetailStats(
        overdue_count=overdue_count,
        upcoming_count=upcoming_count,
        usage_unit=usage_unit,
        current_hours=current_hours,
        latest_hours=latest_hours,
        average_l_per_hr=average_l_per_hr,
        average_cost_per_hr=average_cost_per_hr,
        secondary_usage_enabled=secondary_usage_enabled,
        latest_odometer_km=latest_odometer_km,
        latest_odometer_date=latest_odometer_date,
        last_service_date=last_service_date,
        last_fillup_date=last_fillup_date,
        spent_this_year=service_spent + fuel_spent + def_spent,
        year=year,
    )


@router.get("/{vin}/detail-stats", response_model=VehicleDetailStats)
async def get_vehicle_detail_stats(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> VehicleDetailStats:
    """Read-aggregation for the Vehicle Detail hero + key-facts strip.

    Requires READ access to the vehicle (owner, admin, or a read/write share).
    Returns 404 if the vehicle does not exist, 403 if the caller lacks access.
    """
    await get_vehicle_or_403(vin, current_user, db)  # 404/403 gate before any vin-filtered query
    return await _vehicle_detail_stats(db, vin)


@router.post("", response_model=VehicleResponse, status_code=201)
async def create_vehicle(
    vehicle_data: VehicleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Create a new vehicle.

    **Args:**
    - **vehicle_data**: Vehicle information including VIN

    **Returns:**
    - Created vehicle details

    **Raises:**
    - **400**: VIN already exists
    - **500**: Database error

    **Security:**
    - Vehicle is automatically assigned to the creating user
    - Admin users can also create vehicles
    """
    service = VehicleService(db)
    vehicle = await service.create_vehicle(vehicle_data, current_user)

    return VehicleResponse.model_validate(vehicle)


@router.put("/{vin}", response_model=VehicleResponse)
async def update_vehicle(
    vin: str,
    vehicle_data: VehicleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Update an existing vehicle.

    **Args:**
    - **vin**: Vehicle VIN to update
    - **vehicle_data**: Updated vehicle information

    **Returns:**
    - Updated vehicle details

    **Raises:**
    - **404**: Vehicle not found
    - **403**: Not authorized to update this vehicle
    - **500**: Database error

    **Security:**
    - Users can only update their own vehicles
    - Admin users can update all vehicles
    """
    service = VehicleService(db)
    vehicle = await service.update_vehicle(vin, vehicle_data, current_user)

    return VehicleResponse.model_validate(vehicle)


@router.delete("/{vin}", status_code=204)
async def delete_vehicle(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Delete a vehicle.

    **Args:**
    - **vin**: Vehicle VIN to delete

    **Raises:**
    - **404**: Vehicle not found
    - **403**: Not authorized to delete this vehicle
    - **500**: Database error

    **Security:**
    - Users can only delete their own vehicles
    - Admin users can delete all vehicles
    """
    service = VehicleService(db)
    await service.delete_vehicle(vin, current_user)

    return None


# Trailer Details endpoints


@router.get("/{vin}/trailer", response_model=TrailerDetailsResponse)
async def get_trailer_details(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Get trailer details for a vehicle.

    **Security:**
    - Users can only access trailer details for their own vehicles
    - Admin users can access all trailer details
    """

    vin = vin.upper().strip()

    # Check vehicle ownership first
    await get_vehicle_or_403(vin, current_user, db)

    result = await db.execute(select(TrailerDetails).where(TrailerDetails.vin == vin))
    trailer = result.scalar_one_or_none()

    if not trailer:
        raise HTTPException(status_code=404, detail=f"Trailer details not found for VIN {vin}")

    return TrailerDetailsResponse.model_validate(trailer)


@router.post("/{vin}/trailer", response_model=TrailerDetailsResponse, status_code=201)
async def create_trailer_details(
    vin: str,
    trailer_data: TrailerDetailsCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Create trailer details for a vehicle.

    **Security:**
    - Users can only create trailer details for their own vehicles
    - Admin users can create trailer details for all vehicles
    """

    vin = vin.upper().strip()

    try:
        # Child-record write -> write-share required (D-4).
        _ = await get_vehicle_or_403(vin, current_user, db, require_write=True)

        # Check if trailer details already exist
        result = await db.execute(select(TrailerDetails).where(TrailerDetails.vin == vin))
        existing = result.scalar_one_or_none()

        if existing:
            raise HTTPException(
                status_code=400, detail=f"Trailer details already exist for VIN {vin}"
            )

        # Create trailer details
        trailer_data.vin = vin
        payload = trailer_data.model_dump()
        payload["tow_vehicle_vin"] = await _validate_tow_vehicle_vin(
            db, current_user, payload.get("tow_vehicle_vin")
        )
        trailer = TrailerDetails(**payload)
        db.add(trailer)
        await db.commit()
        await db.refresh(trailer)

        logger.info("Created trailer details for: %s", sanitize_for_log(vin))

        return TrailerDetailsResponse.model_validate(trailer)

    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(
            "Database constraint violation creating trailer details for %s: %s",
            sanitize_for_log(vin),
            sanitize_for_log(str(e)),
        )
        raise HTTPException(status_code=409, detail=f"Trailer details already exist for VIN {vin}")
    except OperationalError as e:
        await db.rollback()
        logger.error(
            "Database connection error creating trailer details for %s: %s",
            sanitize_for_log(vin),
            sanitize_for_log(str(e)),
        )
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")


@router.put("/{vin}/trailer", response_model=TrailerDetailsResponse)
async def update_trailer_details(
    vin: str,
    trailer_data: TrailerDetailsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Update trailer details for a vehicle.

    **Security:**
    - Users can only update trailer details for their own vehicles
    - Admin users can update trailer details for all vehicles
    """

    vin = vin.upper().strip()

    try:
        # Child-record write -> write-share required (D-4).
        await get_vehicle_or_403(vin, current_user, db, require_write=True)

        # Get existing trailer details
        result = await db.execute(select(TrailerDetails).where(TrailerDetails.vin == vin))
        trailer = result.scalar_one_or_none()

        if not trailer:
            raise HTTPException(status_code=404, detail=f"Trailer details not found for VIN {vin}")

        # Update fields
        update_data = trailer_data.model_dump(exclude_unset=True)
        if "tow_vehicle_vin" in update_data:
            update_data["tow_vehicle_vin"] = await _validate_tow_vehicle_vin(
                db, current_user, update_data.get("tow_vehicle_vin")
            )
        for field, value in update_data.items():
            setattr(trailer, field, value)

        await db.commit()
        await db.refresh(trailer)

        logger.info("Updated trailer details for: %s", sanitize_for_log(vin))

        return TrailerDetailsResponse.model_validate(trailer)

    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error(
            "Database constraint violation updating trailer details for %s: %s",
            sanitize_for_log(vin),
            sanitize_for_log(str(e)),
        )
        raise HTTPException(status_code=409, detail="Database constraint violation")
    except OperationalError as e:
        await db.rollback()
        logger.error(
            "Database connection error updating trailer details for %s: %s",
            sanitize_for_log(vin),
            sanitize_for_log(str(e)),
        )
        raise HTTPException(status_code=503, detail="Database temporarily unavailable")


@router.get("/{vin}/towed-trailers", response_model=list[VehicleResponse])
async def list_towed_trailers(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """List trailer vehicles paired to this tow vehicle via TrailerDetails.tow_vehicle_vin."""
    vin = vin.upper().strip()
    await get_vehicle_or_403(vin, current_user, db)
    result = await db.execute(
        select(Vehicle)
        .join(TrailerDetails, TrailerDetails.vin == Vehicle.vin)
        .where(TrailerDetails.tow_vehicle_vin == vin)
        .order_by(Vehicle.nickname)
    )
    return [VehicleResponse.model_validate(v) for v in result.scalars().all()]


# ========== ARCHIVE ENDPOINTS ==========


@router.post("/{vin}/archive", response_model=VehicleResponse)
async def archive_vehicle(
    vin: str,
    archive_data: VehicleArchiveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """
    Archive a vehicle (soft delete).

    **Args:**
    - **vin**: Vehicle VIN
    - **archive_data**: Archive metadata (reason, price, date, notes, visible)

    **Returns:**
    - Updated vehicle with archive metadata

    **Raises:**
    - **404**: Vehicle not found
    - **403**: Not authorized (when authenticated)
    """
    vin = vin.upper().strip()

    # Archive/unarchive/visibility are OWNER-only vehicle-core ops (D-2). With
    # require_auth (not optional_auth), current_user is None only in none-mode;
    # get_vehicle_for_owner_or_403 then enforces owner/admin (a no-token request
    # in local/oidc already 401s at the dependency).
    vehicle = await get_vehicle_for_owner_or_403(vin, current_user, db)

    # Set archive fields
    vehicle.archived_at = utc_now()
    vehicle.archive_reason = archive_data.reason
    vehicle.archive_sale_price = archive_data.sale_price
    vehicle.archive_sale_date = archive_data.sale_date
    vehicle.archive_notes = archive_data.notes
    vehicle.archived_visible = archive_data.visible

    await db.commit()
    await db.refresh(vehicle)

    logger.info(
        "Archived vehicle %s (reason: %s)",
        sanitize_for_log(vin),
        sanitize_for_log(archive_data.reason),
    )
    return VehicleResponse.model_validate(vehicle)


@router.post("/{vin}/unarchive", response_model=VehicleResponse)
async def unarchive_vehicle(
    vin: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """
    Restore an archived vehicle to active status.

    **Args:**
    - **vin**: Vehicle VIN

    **Returns:**
    - Updated vehicle (active)

    **Raises:**
    - **404**: Vehicle not found
    - **403**: Not authorized (when authenticated)
    - **400**: Vehicle is not archived
    """
    vin = vin.upper().strip()

    # Archive/unarchive/visibility are OWNER-only vehicle-core ops (D-2). With
    # require_auth (not optional_auth), current_user is None only in none-mode;
    # get_vehicle_for_owner_or_403 then enforces owner/admin (a no-token request
    # in local/oidc already 401s at the dependency).
    vehicle = await get_vehicle_for_owner_or_403(vin, current_user, db)

    if not vehicle.archived_at:
        raise HTTPException(status_code=400, detail="Vehicle is not archived")

    # Clear archive fields
    vehicle.archived_at = None
    vehicle.archive_reason = None
    vehicle.archive_sale_price = None
    vehicle.archive_sale_date = None
    vehicle.archive_notes = None
    vehicle.archived_visible = True

    await db.commit()
    await db.refresh(vehicle)

    logger.info("Unarchived vehicle %s", sanitize_for_log(vin))
    return VehicleResponse.model_validate(vehicle)


@router.get("/archived/list", response_model=VehicleListResponse)
async def list_archived_vehicles(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """
    Get list of archived vehicles (user's own only in auth mode, all in none mode).

    **Query Parameters:**
    - **skip**: Number of records to skip
    - **limit**: Maximum number of records to return

    **Returns:**
    - List of archived vehicles with total count

    **Security:**
    - When authenticated: Users see ONLY their own archived vehicles (admin does NOT see all)
    - When auth_mode=none: Returns all archived vehicles
    """
    # Build query for archived vehicles
    if current_user:
        # Auth mode: user's archived vehicles + vehicles with NULL user_id (created in none mode)
        logger.info(f"Fetching archived vehicles for user_id={current_user.id}")
        query = (
            select(Vehicle)
            .where(
                ((Vehicle.user_id == current_user.id) | (Vehicle.user_id.is_(None))),
                Vehicle.archived_at.isnot(None),
            )
            .order_by(Vehicle.archived_at.desc())
        )
    else:
        # No auth mode: all archived vehicles
        logger.info("Fetching all archived vehicles (auth_mode=none)")
        query = (
            select(Vehicle)
            .where(Vehicle.archived_at.isnot(None))
            .order_by(Vehicle.archived_at.desc())
        )

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    result = await db.execute(count_query)
    total = result.scalar() or 0

    logger.info(f"Found {total} archived vehicles")

    # Get paginated results
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    vehicles = result.scalars().all()

    logger.info(f"Returning {len(vehicles)} archived vehicles")

    return VehicleListResponse(
        vehicles=[VehicleResponse.model_validate(v) for v in vehicles], total=total
    )


@router.patch("/{vin}/archive/visibility", response_model=VehicleResponse)
async def toggle_archived_visibility(
    vin: str,
    visible: bool,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """
    Toggle visibility of archived vehicle in main list.

    **Args:**
    - **vin**: Vehicle VIN
    - **visible**: Whether to show in main list

    **Returns:**
    - Updated vehicle

    **Raises:**
    - **404**: Vehicle not found
    - **403**: Not authorized (when authenticated)
    - **400**: Vehicle is not archived
    """
    vin = vin.upper().strip()

    # Archive/unarchive/visibility are OWNER-only vehicle-core ops (D-2). With
    # require_auth (not optional_auth), current_user is None only in none-mode;
    # get_vehicle_for_owner_or_403 then enforces owner/admin (a no-token request
    # in local/oidc already 401s at the dependency).
    vehicle = await get_vehicle_for_owner_or_403(vin, current_user, db)

    if not vehicle.archived_at:
        raise HTTPException(status_code=400, detail="Vehicle is not archived")

    vehicle.archived_visible = visible

    await db.commit()
    await db.refresh(vehicle)

    logger.info("Set archived vehicle %s visibility to %s", sanitize_for_log(vin), visible)
    return VehicleResponse.model_validate(vehicle)

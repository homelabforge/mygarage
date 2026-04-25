from datetime import date as date_type
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    Document,
    FuelRecord,
    Note,
    OdometerRecord,
    Reminder,
    ServiceVisit,
    Vehicle,
)
from app.models.user import User
from app.models.vehicle_share import VehicleShare
from app.schemas.dashboard import DashboardResponse, VehicleStatistics
from app.services.auth import optional_auth
from app.services.fuel_service import calculate_l_per_100km

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# Photo directory configuration
PHOTO_DIR = Path("/data/photos")
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


async def calculate_vehicle_stats(
    db: AsyncSession,
    vehicle: Vehicle,
    is_shared_with_me: bool = False,
    shared_by_username: str | None = None,
    share_permission: str | None = None,
) -> VehicleStatistics:
    """Calculate statistics for a single vehicle"""

    # Count records
    service_count = await db.scalar(
        select(func.count(ServiceVisit.id)).where(ServiceVisit.vin == vehicle.vin)
    )
    fuel_count = await db.scalar(
        select(func.count(FuelRecord.id)).where(FuelRecord.vin == vehicle.vin)
    )
    odometer_count = await db.scalar(
        select(func.count(OdometerRecord.id)).where(OdometerRecord.vin == vehicle.vin)
    )
    maintenance_count = await db.scalar(
        select(func.count(Reminder.id)).where(Reminder.vin == vehicle.vin)
    )
    document_count = await db.scalar(
        select(func.count(Document.id)).where(Document.vin == vehicle.vin)
    )
    note_count = await db.scalar(select(func.count(Note.id)).where(Note.vin == vehicle.vin))

    # Count photos from filesystem
    photo_count = 0
    vehicle_photo_dir = PHOTO_DIR / vehicle.vin
    if vehicle_photo_dir.exists():
        photo_count = sum(
            1
            for photo_file in vehicle_photo_dir.iterdir()
            if photo_file.is_file() and photo_file.suffix.lower() in ALLOWED_EXTENSIONS
        )

    # Get latest service date
    latest_service = await db.scalar(
        select(ServiceVisit.date)
        .where(ServiceVisit.vin == vehicle.vin)
        .order_by(ServiceVisit.date.desc())
        .limit(1)
    )

    # Get latest fuel date
    latest_fuel = await db.scalar(
        select(FuelRecord.date)
        .where(FuelRecord.vin == vehicle.vin)
        .order_by(FuelRecord.date.desc())
        .limit(1)
    )

    # Get latest odometer_km reading and date
    latest_odometer_record = await db.execute(
        select(OdometerRecord.odometer_km, OdometerRecord.date)
        .where(OdometerRecord.vin == vehicle.vin)
        .order_by(OdometerRecord.date.desc())
        .limit(1)
    )
    latest_odometer = latest_odometer_record.first()
    latest_odometer_km: Decimal | None = None
    latest_odometer_date: date_type | None = None
    if latest_odometer:
        latest_odometer_km = latest_odometer[0]
        latest_odometer_date = latest_odometer[1]

    # Count upcoming and overdue reminders
    today = date_type.today()
    pending_reminders_result = await db.execute(
        select(Reminder).where(Reminder.vin == vehicle.vin, Reminder.status == "pending")
    )
    pending_reminders = pending_reminders_result.scalars().all()

    # Get current odometer_km for overdue check
    current_odometer_record = await db.execute(
        select(OdometerRecord.odometer_km)
        .where(OdometerRecord.vin == vehicle.vin)
        .order_by(OdometerRecord.date.desc())
        .limit(1)
    )
    current_odometer_km = current_odometer_record.scalar_one_or_none()

    upcoming_count = 0
    overdue_count = 0
    for reminder in pending_reminders:
        is_overdue = False
        if reminder.due_date and reminder.due_date <= today:
            is_overdue = True
        if (
            reminder.due_mileage_km
            and current_odometer_km
            and current_odometer_km >= reminder.due_mileage_km
        ):
            is_overdue = True
        if is_overdue:
            overdue_count += 1
        else:
            upcoming_count += 1

    # Calculate average L/100km from fuel records
    fuel_records_result = await db.execute(
        select(FuelRecord).where(FuelRecord.vin == vehicle.vin).order_by(FuelRecord.date.desc())
    )
    fuel_records_list = list(fuel_records_result.scalars().all())

    l_per_100km_values: list[Decimal] = []
    for i in range(len(fuel_records_list)):
        if i < len(fuel_records_list) - 1:
            value = calculate_l_per_100km(fuel_records_list[i], fuel_records_list[i + 1])
            if value:
                l_per_100km_values.append(value)

    average_l_per_100km: Decimal | None = None
    recent_l_per_100km: Decimal | None = None
    if l_per_100km_values:
        average_l_per_100km = round(sum(l_per_100km_values) / Decimal(len(l_per_100km_values)), 2)
        # Recent L/100km is average of last 3 fill-ups
        recent_window = l_per_100km_values[:3]
        recent_l_per_100km = round(sum(recent_window) / Decimal(len(recent_window)), 2)

    # Get main photo URL from Vehicle.main_photo field
    main_photo_url: str | None = None
    if vehicle.main_photo:
        # main_photo is stored as "VIN/filename.jpg"
        # Extract just the filename
        from pathlib import Path

        filename = Path(vehicle.main_photo).name
        main_photo_url = f"/api/vehicles/{vehicle.vin}/photos/{filename}"

    return VehicleStatistics(
        vin=vehicle.vin,
        year=vehicle.year,
        make=vehicle.make,
        model=vehicle.model,
        main_photo_url=main_photo_url,
        total_service_records=service_count or 0,
        total_fuel_records=fuel_count or 0,
        total_odometer_records=odometer_count or 0,
        total_maintenance_items=maintenance_count or 0,
        total_documents=document_count or 0,
        total_notes=note_count or 0,
        total_photos=photo_count or 0,
        latest_service_date=latest_service,
        latest_fuel_date=latest_fuel,
        latest_odometer_km=latest_odometer_km,
        latest_odometer_date=latest_odometer_date,
        upcoming_maintenance_count=upcoming_count or 0,
        overdue_maintenance_count=overdue_count or 0,
        average_l_per_100km=average_l_per_100km,
        recent_l_per_100km=recent_l_per_100km,
        archived_at=vehicle.archived_at,
        archived_visible=vehicle.archived_visible,
        is_shared_with_me=is_shared_with_me,
        shared_by_username=shared_by_username,
        share_permission=share_permission,
    )


@router.get("", response_model=DashboardResponse)
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(optional_auth),
):
    """
    Get complete dashboard with statistics for all vehicles.

    For authenticated users: Shows owned vehicles + shared vehicles.
    For unauthenticated: Shows all active vehicles (legacy behavior).
    Shows active vehicles + archived vehicles where archived_visible=True.
    """
    vehicle_stats = []

    if current_user and not current_user.is_admin:
        # Non-admin user: get owned vehicles
        owned_result = await db.execute(
            select(Vehicle).where(
                Vehicle.user_id == current_user.id,
                (Vehicle.archived_at.is_(None))
                | ((Vehicle.archived_at.isnot(None)) & (Vehicle.archived_visible.is_(True))),
            )
        )
        owned_vehicles = owned_result.scalars().all()

        # Get stats for owned vehicles
        for vehicle in owned_vehicles:
            stats = await calculate_vehicle_stats(db, vehicle)
            vehicle_stats.append(stats)

        # Get shared vehicles
        shared_result = await db.execute(
            select(VehicleShare, Vehicle, User)
            .join(Vehicle, VehicleShare.vehicle_vin == Vehicle.vin)
            .join(User, Vehicle.user_id == User.id)
            .where(
                VehicleShare.user_id == current_user.id,
                (Vehicle.archived_at.is_(None))
                | ((Vehicle.archived_at.isnot(None)) & (Vehicle.archived_visible.is_(True))),
            )
        )
        shared_rows = shared_result.all()

        # Get stats for shared vehicles
        for share, vehicle, owner in shared_rows:
            stats = await calculate_vehicle_stats(
                db,
                vehicle,
                is_shared_with_me=True,
                shared_by_username=owner.username,
                share_permission=share.permission,
            )
            vehicle_stats.append(stats)
    else:
        # Admin or unauthenticated: get all vehicles (legacy behavior)
        result = await db.execute(
            select(Vehicle).where(
                (Vehicle.archived_at.is_(None))
                | ((Vehicle.archived_at.isnot(None)) & (Vehicle.archived_visible.is_(True)))
            )
        )
        vehicles = result.scalars().all()

        # Calculate statistics for each vehicle
        for vehicle in vehicles:
            stats = await calculate_vehicle_stats(db, vehicle)
            vehicle_stats.append(stats)

    # Calculate garage-wide totals
    total_service = sum(v.total_service_records for v in vehicle_stats)
    total_fuel = sum(v.total_fuel_records for v in vehicle_stats)
    total_maintenance_items = sum(v.total_maintenance_items for v in vehicle_stats)
    total_documents = sum(v.total_documents for v in vehicle_stats)
    total_notes = sum(v.total_notes for v in vehicle_stats)
    total_photos = sum(v.total_photos for v in vehicle_stats)

    return DashboardResponse(
        total_vehicles=len(vehicle_stats),
        vehicles=vehicle_stats,
        total_service_records=total_service,
        total_fuel_records=total_fuel,
        total_maintenance_items=total_maintenance_items,
        total_documents=total_documents,
        total_notes=total_notes,
        total_photos=total_photos,
    )

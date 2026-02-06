from datetime import date as date_type
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
    ServiceRecord,
    Vehicle,
)
from app.models.user import User
from app.models.vehicle_share import VehicleShare
from app.schemas.dashboard import DashboardResponse, VehicleStatistics
from app.services.auth import optional_auth
from app.services.fuel_service import calculate_mpg

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
        select(func.count(ServiceRecord.id)).where(ServiceRecord.vin == vehicle.vin)
    )
    fuel_count = await db.scalar(
        select(func.count(FuelRecord.id)).where(FuelRecord.vin == vehicle.vin)
    )
    odometer_count = await db.scalar(
        select(func.count(OdometerRecord.id)).where(OdometerRecord.vin == vehicle.vin)
    )
    reminder_count = await db.scalar(
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
        select(ServiceRecord.date)
        .where(ServiceRecord.vin == vehicle.vin)
        .order_by(ServiceRecord.date.desc())
        .limit(1)
    )

    # Get latest fuel date
    latest_fuel = await db.scalar(
        select(FuelRecord.date)
        .where(FuelRecord.vin == vehicle.vin)
        .order_by(FuelRecord.date.desc())
        .limit(1)
    )

    # Get latest odometer reading and date
    latest_odometer_record = await db.execute(
        select(OdometerRecord.mileage, OdometerRecord.date)
        .where(OdometerRecord.vin == vehicle.vin)
        .order_by(OdometerRecord.date.desc())
        .limit(1)
    )
    latest_odometer = latest_odometer_record.first()
    latest_odometer_reading: int | None = None
    latest_odometer_date: date_type | None = None
    if latest_odometer:
        latest_odometer_reading = latest_odometer[0]
        latest_odometer_date = latest_odometer[1]

    # Count upcoming and overdue reminders
    today = date_type.today()
    upcoming_count = await db.scalar(
        select(func.count(Reminder.id)).where(
            Reminder.vin == vehicle.vin,
            Reminder.is_completed.is_(False),
            Reminder.due_date >= today,
        )
    )
    overdue_count = await db.scalar(
        select(func.count(Reminder.id)).where(
            Reminder.vin == vehicle.vin,
            Reminder.is_completed.is_(False),
            Reminder.due_date < today,
        )
    )

    # Calculate average MPG from fuel records
    fuel_records_result = await db.execute(
        select(FuelRecord).where(FuelRecord.vin == vehicle.vin).order_by(FuelRecord.date.desc())
    )
    fuel_records_list = list(fuel_records_result.scalars().all())

    mpg_values = []
    for i in range(len(fuel_records_list)):
        if i < len(fuel_records_list) - 1:
            mpg = calculate_mpg(fuel_records_list[i], fuel_records_list[i + 1])
            if mpg:
                mpg_values.append(float(mpg))

    average_mpg: float | None = None
    recent_mpg: float | None = None
    if mpg_values:
        average_mpg = round(sum(mpg_values) / len(mpg_values), 2)
        # Recent MPG is average of last 3 fill-ups
        recent_mpg = round(sum(mpg_values[:3]) / min(3, len(mpg_values)), 2)

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
        total_reminders=reminder_count or 0,
        total_documents=document_count or 0,
        total_notes=note_count or 0,
        total_photos=photo_count or 0,
        latest_service_date=latest_service,
        latest_fuel_date=latest_fuel,
        latest_odometer_reading=latest_odometer_reading,
        latest_odometer_date=latest_odometer_date,
        upcoming_reminders_count=upcoming_count or 0,
        overdue_reminders_count=overdue_count or 0,
        average_mpg=average_mpg,
        recent_mpg=recent_mpg,
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
    total_reminders = sum(v.total_reminders for v in vehicle_stats)
    total_documents = sum(v.total_documents for v in vehicle_stats)
    total_notes = sum(v.total_notes for v in vehicle_stats)
    total_photos = sum(v.total_photos for v in vehicle_stats)

    return DashboardResponse(
        total_vehicles=len(vehicle_stats),
        vehicles=vehicle_stats,
        total_service_records=total_service,
        total_fuel_records=total_fuel,
        total_reminders=total_reminders,
        total_documents=total_documents,
        total_notes=total_notes,
        total_photos=total_photos,
    )

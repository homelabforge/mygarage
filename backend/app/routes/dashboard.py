from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date as date_type
from typing import Optional
from pathlib import Path

from app.database import get_db
from app.models import Vehicle, ServiceRecord, FuelRecord, OdometerRecord, Reminder, Document, Note
from app.models.user import User
from app.schemas.dashboard import DashboardResponse, VehicleStatistics
from app.services.fuel_service import calculate_mpg
from app.services.auth import optional_auth

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# Photo directory configuration
PHOTO_DIR = Path("/data/photos")
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}


async def calculate_vehicle_stats(
    db: AsyncSession, vehicle: Vehicle
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
    note_count = await db.scalar(
        select(func.count(Note.id)).where(Note.vin == vehicle.vin)
    )

    # Count photos from filesystem
    photo_count = 0
    vehicle_photo_dir = PHOTO_DIR / vehicle.vin
    if vehicle_photo_dir.exists():
        photo_count = sum(
            1 for photo_file in vehicle_photo_dir.iterdir()
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
    latest_odometer_reading: Optional[int] = None
    latest_odometer_date: Optional[date_type] = None
    if latest_odometer:
        latest_odometer_reading = latest_odometer[0]
        latest_odometer_date = latest_odometer[1]

    # Count upcoming and overdue reminders
    today = date_type.today()
    upcoming_count = await db.scalar(
        select(func.count(Reminder.id))
        .where(
            Reminder.vin == vehicle.vin,
            Reminder.is_completed == False,
            Reminder.due_date >= today,
        )
    )
    overdue_count = await db.scalar(
        select(func.count(Reminder.id))
        .where(
            Reminder.vin == vehicle.vin,
            Reminder.is_completed == False,
            Reminder.due_date < today,
        )
    )

    # Calculate average MPG from fuel records
    fuel_records_result = await db.execute(
        select(FuelRecord)
        .where(FuelRecord.vin == vehicle.vin)
        .order_by(FuelRecord.date.desc())
    )
    fuel_records_list = list(fuel_records_result.scalars().all())

    mpg_values = []
    for i in range(len(fuel_records_list)):
        if i < len(fuel_records_list) - 1:
            mpg = calculate_mpg(fuel_records_list[i], fuel_records_list[i + 1])
            if mpg:
                mpg_values.append(float(mpg))

    average_mpg: Optional[float] = None
    recent_mpg: Optional[float] = None
    if mpg_values:
        average_mpg = round(sum(mpg_values) / len(mpg_values), 2)
        # Recent MPG is average of last 3 fill-ups
        recent_mpg = round(sum(mpg_values[:3]) / min(3, len(mpg_values)), 2)

    # Get main photo URL from Vehicle.main_photo field
    main_photo_url: Optional[str] = None
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
    )


@router.get("", response_model=DashboardResponse)
async def get_dashboard(db: AsyncSession = Depends(get_db), current_user: Optional[User] = Depends(optional_auth)):
    """
    Get complete dashboard with statistics for all vehicles
    """
    # Get all vehicles
    result = await db.execute(select(Vehicle))
    vehicles = result.scalars().all()

    # Calculate statistics for each vehicle
    vehicle_stats = []
    for vehicle in vehicles:
        stats = await calculate_vehicle_stats(db, vehicle)
        vehicle_stats.append(stats)

    # Calculate fleet-wide totals
    total_service = sum(v.total_service_records for v in vehicle_stats)
    total_fuel = sum(v.total_fuel_records for v in vehicle_stats)
    total_reminders = sum(v.total_reminders for v in vehicle_stats)
    total_documents = sum(v.total_documents for v in vehicle_stats)
    total_notes = sum(v.total_notes for v in vehicle_stats)
    total_photos = sum(v.total_photos for v in vehicle_stats)

    return DashboardResponse(
        total_vehicles=len(vehicles),
        vehicles=vehicle_stats,
        total_service_records=total_service,
        total_fuel_records=total_fuel,
        total_reminders=total_reminders,
        total_documents=total_documents,
        total_notes=total_notes,
        total_photos=total_photos,
    )

from pydantic import BaseModel
from typing import Optional
from datetime import date as date_type, datetime


class VehicleStatistics(BaseModel):
    """Statistics for a single vehicle"""

    vin: str
    year: int
    make: str
    model: str
    main_photo_url: Optional[str] = None

    # Counts
    total_service_records: int
    total_fuel_records: int
    total_odometer_records: int
    total_reminders: int
    total_documents: int
    total_notes: int
    total_photos: int

    # Recent activity
    latest_service_date: Optional[date_type] = None
    latest_fuel_date: Optional[date_type] = None
    latest_odometer_reading: Optional[int] = None
    latest_odometer_date: Optional[date_type] = None

    # Upcoming reminders
    upcoming_reminders_count: int
    overdue_reminders_count: int

    # Fuel statistics
    average_mpg: Optional[float] = None
    recent_mpg: Optional[float] = None

    # Archive status
    archived_at: Optional[datetime] = None
    archived_visible: bool = True

    class Config:
        from_attributes = True


class DashboardResponse(BaseModel):
    """Complete dashboard data"""

    total_vehicles: int
    vehicles: list[VehicleStatistics]

    # Garage-wide totals
    total_service_records: int
    total_fuel_records: int
    total_reminders: int
    total_documents: int
    total_notes: int
    total_photos: int

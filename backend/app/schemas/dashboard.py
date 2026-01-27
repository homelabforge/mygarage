from datetime import date as date_type
from datetime import datetime

from pydantic import BaseModel


class VehicleStatistics(BaseModel):
    """Statistics for a single vehicle"""

    vin: str
    year: int
    make: str
    model: str
    main_photo_url: str | None = None

    # Counts
    total_service_records: int
    total_fuel_records: int
    total_odometer_records: int
    total_reminders: int
    total_documents: int
    total_notes: int
    total_photos: int

    # Recent activity
    latest_service_date: date_type | None = None
    latest_fuel_date: date_type | None = None
    latest_odometer_reading: int | None = None
    latest_odometer_date: date_type | None = None

    # Upcoming reminders
    upcoming_reminders_count: int
    overdue_reminders_count: int

    # Fuel statistics
    average_mpg: float | None = None
    recent_mpg: float | None = None

    # Archive status
    archived_at: datetime | None = None
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

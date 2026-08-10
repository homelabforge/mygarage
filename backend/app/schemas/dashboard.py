from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class VehicleStatistics(BaseModel):
    """Statistics for a single vehicle"""

    vin: str
    year: int | None = None
    make: str | None = None
    model: str | None = None
    vehicle_type: str | None = None
    main_photo_url: str | None = None

    # Usage tracking dimension — drives the odometer/hours relabel on the card
    usage_unit: str = "distance"
    # Kept for API compat only — NO LONGER the display source (R2-H1). The
    # canonical current-hours reading is `latest_hours` below, derived via
    # `latest_engine_hours_and_date` from `hours_records`, never this column.
    current_hours: Decimal | None = None
    # Canonical latest engine-hours reading (the §1 helper) + hours-economy
    # figures, mirroring latest_odometer_km / average_l_per_100km below.
    # Null for a pure-distance vehicle.
    latest_hours: Decimal | None = None
    average_l_per_hr: Decimal | None = None
    average_cost_per_hr: Decimal | None = None
    secondary_usage_enabled: bool = False

    # Counts
    total_service_records: int
    total_fuel_records: int
    total_odometer_records: int
    total_maintenance_items: int
    total_documents: int
    total_notes: int
    total_photos: int

    # Recent activity (metric-canonical: km)
    latest_service_date: date_type | None = None
    latest_fuel_date: date_type | None = None
    latest_odometer_km: Decimal | None = None
    latest_odometer_date: date_type | None = None

    # Upcoming maintenance
    upcoming_maintenance_count: int
    overdue_maintenance_count: int

    # Fuel statistics (metric-canonical: L/100km)
    average_l_per_100km: Decimal | None = None
    recent_l_per_100km: Decimal | None = None

    # Archive status
    archived_at: datetime | None = None
    archived_visible: bool = True

    # Sharing info (for shared vehicles)
    is_shared_with_me: bool = False
    shared_by_username: str | None = None
    share_permission: str | None = None  # 'read' or 'write'
    owner_relationship: str | None = None
    owner_relationship_custom: str | None = None

    class Config:
        from_attributes = True


class FleetNextDue(BaseModel):
    """Soonest pending reminder across the visible fleet."""

    vin: str
    label: str
    due_date: date_type | None = None
    due_mileage_km: Decimal | None = None

    class Config:
        from_attributes = True


class FleetHealth(BaseModel):
    """Fleet-wide health summary for the dashboard strip (read aggregation)."""

    overdue_count: int
    upcoming_30d_count: int
    year: int
    spent_this_year: Decimal
    next_due: FleetNextDue | None = None


class DashboardResponse(BaseModel):
    """Complete dashboard data"""

    total_vehicles: int
    vehicles: list[VehicleStatistics]
    multi_user_enabled: bool = False

    # Garage-wide totals
    total_service_records: int
    total_fuel_records: int
    total_maintenance_items: int
    total_documents: int
    total_notes: int
    total_photos: int

    # Fleet-health strip (P4)
    fleet_health: FleetHealth

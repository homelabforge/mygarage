from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.schemas.vehicle import LenientUsageUnit, LenientVehicleType
from app.utils.unit_resolution import LenientDistanceUnit


class TowVehicleSummary(BaseModel):
    """The vehicle a trailer is paired with, for the card's "Towed by" row."""

    model_config = {"from_attributes": True}

    vin: str
    year: int | None = None
    make: str | None = None
    model: str | None = None


class VehicleStatistics(BaseModel):
    """Statistics for a single vehicle"""

    vin: str
    year: int | None = None
    make: str | None = None
    model: str | None = None
    vehicle_type: LenientVehicleType = None
    main_photo_url: str | None = None

    # Usage tracking dimension — drives the odometer/hours relabel on the card
    usage_unit: LenientUsageUnit = "distance"
    # The vehicle's own odometer unit; null follows the viewer (#172).
    distance_unit: LenientDistanceUnit = None
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

    # Reminders: upcoming is pending-not-overdue; due_soon is its subset expected
    # within DUE_SOON_WINDOW, or, when the rates can't project a date, at least
    # DUE_SOON_PROGRESS along its usage span (#192 D2). The photo badge and the
    # fleet strip read it; see reminder_service.reminder_due_status.
    upcoming_maintenance_count: int
    due_soon_maintenance_count: int
    overdue_maintenance_count: int

    # Fuel statistics (metric-canonical: L/100km).
    #
    # These two leave towing tanks out, matching
    # `calculate_average_l_per_100km`'s default and the vehicle's own Fuel tab;
    # `recent_l_per_100km` covers the last 3 of those tanks. Null when the
    # vehicle has no non-towing figure at all, which is reachable: a dedicated
    # tow rig may have hauled on every fill-up. All are total fuel over total
    # distance.
    average_l_per_100km: Decimal | None = None
    recent_l_per_100km: Decimal | None = None
    # The towing tanks alone (issue #181). Null when the vehicle never tows.
    towing_l_per_100km: Decimal | None = None

    # Towable cards (fifth wheels, travel trailers): the trailer-details pairing,
    # and the trailer's economy, litres of propane per average month across its
    # bottle refills (`propane_l_per_month` in fuel_service) plus the same over
    # the last 3 refills. Null without a pairing / fewer than two refills.
    tow_vehicle: TowVehicleSummary | None = None
    propane_l_per_month: Decimal | None = None
    recent_propane_l_per_month: Decimal | None = None

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
    # The due vehicle's own odometer unit; null follows the viewer (#172).
    distance_unit: LenientDistanceUnit = None

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

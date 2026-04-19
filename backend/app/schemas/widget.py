"""Pydantic response models for /api/widget/* endpoints.

The API returns the full field set; the homepage `customapi` widget picks
which 4 to display via its own `mappings:` block. Field names stay flat and
snake_case so they map directly to homepage's `field:` references.
"""

from datetime import date

from pydantic import BaseModel


class WidgetSummary(BaseModel):
    """Garage-wide aggregates scoped to the key owner's vehicles."""

    total_vehicles: int
    active_vehicles: int
    archived_vehicles: int
    total_overdue_maintenance: int
    total_upcoming_maintenance: int
    total_service_records: int
    total_fuel_records: int
    total_documents: int
    total_notes: int
    total_photos: int


class WidgetVehicleRef(BaseModel):
    """Minimal VIN + label pair used by the discovery list."""

    vin: str
    label: str


class WidgetVehicleList(BaseModel):
    vehicles: list[WidgetVehicleRef]


class WidgetVehicle(BaseModel):
    """Per-vehicle rollup. Four of these fields render as a homepage tile."""

    label: str
    year: int | None = None
    make: str | None = None
    model: str | None = None

    odometer: int | None = None
    odometer_date: date | None = None

    recent_mpg: float | None = None
    average_mpg: float | None = None

    upcoming_maintenance: int
    overdue_maintenance: int

    service_records: int
    fuel_records: int
    last_service_date: date | None = None
    last_fuel_date: date | None = None

    documents: int
    notes: int
    photos: int

"""Calendar schemas for MyGarage API (metric canonical since v2.26.2)."""

from datetime import date as date_type
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.utils.unit_resolution import LenientDistanceUnit


class CalendarEvent(BaseModel):
    """Schema for a calendar event."""

    id: str = Field(..., description="Unique identifier in format 'type-id'")
    type: Literal["maintenance", "insurance", "warranty", "service"] = Field(
        ..., description="Event type"
    )
    title: str = Field(..., description="Event title/description")
    description: str | None = Field(None, description="Additional details")
    date: date_type = Field(..., description="Event date")
    vehicle_vin: str = Field(..., description="Associated vehicle VIN")
    vehicle_nickname: str | None = Field(None, description="Vehicle nickname")
    vehicle_color: str | None = Field(
        None, description="Custom vehicle color for calendar (Phase 3)"
    )
    urgency: Literal["overdue", "high", "medium", "low", "historical"] = Field(
        ..., description="Event urgency level"
    )
    is_recurring: bool = Field(default=False, description="Whether event recurs")
    is_completed: bool = Field(default=False, description="Whether event is completed")
    is_estimated: bool = Field(
        default=False, description="Whether date is estimated from odometer_km (Phase 3)"
    )
    category: Literal["maintenance", "legal", "financial", "history"] = Field(
        ..., description="Event category"
    )
    notes: str | None = Field(None, description="Event notes/comments (Phase 3)")
    due_mileage_km: Decimal | None = Field(
        None, description="Due odometer reading (km) for mileage-based reminders (Phase 3)"
    )
    due_hours: Decimal | None = Field(
        None, description="Due engine-hours reading for hours-based reminders (Phase 6b)"
    )
    status: str | None = Field(
        None, description="Reminder due status (overdue, due_soon, on_track, snoozed)"
    )
    days_until_due: int | None = Field(None, description="Days until due date")
    km_until_due: Decimal | None = Field(None, description="Kilometers until due odometer reading")
    vehicle_distance_unit: LenientDistanceUnit = Field(
        None, description="The vehicle's own odometer unit; null follows the viewer (#172)"
    )
    hours_until_due: Decimal | None = Field(
        None, description="Engine-hours until due hours reading (Phase 6b)"
    )
    tread_depth_mm: Decimal | None = Field(
        None, description="Low-tread reminder's tread depth (mm); null for other events"
    )
    tread_threshold_mm: Decimal | None = Field(
        None, description="Low-tread reminder's minimum tread (mm); null for other events"
    )


class CalendarSummary(BaseModel):
    """Schema for calendar summary statistics."""

    total: int = Field(..., description="Total events")
    overdue: int = Field(..., description="Overdue events")
    upcoming_7_days: int = Field(..., description="Events in next 7 days")
    upcoming_30_days: int = Field(..., description="Events in next 30 days")


class CalendarResponse(BaseModel):
    """Schema for calendar response."""

    events: list[CalendarEvent] = Field(default_factory=list, description="List of calendar events")
    summary: CalendarSummary = Field(..., description="Summary statistics")

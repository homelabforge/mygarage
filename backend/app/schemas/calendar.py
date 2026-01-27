"""Calendar schemas for MyGarage API."""

from datetime import date as date_type
from typing import Literal

from pydantic import BaseModel, Field


class CalendarEvent(BaseModel):
    """Schema for a calendar event."""

    id: str = Field(..., description="Unique identifier in format 'type-id'")
    type: Literal["reminder", "insurance", "warranty", "service"] = Field(
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
        default=False, description="Whether date is estimated from mileage (Phase 3)"
    )
    category: Literal["maintenance", "legal", "financial", "history"] = Field(
        ..., description="Event category"
    )
    notes: str | None = Field(None, description="Event notes/comments (Phase 3)")
    due_mileage: int | None = Field(
        None, description="Due mileage for mileage-based reminders (Phase 3)"
    )


class CalendarSummary(BaseModel):
    """Schema for calendar summary statistics."""

    total: int = Field(..., description="Total events")
    overdue: int = Field(..., description="Overdue events")
    upcoming_7_days: int = Field(..., description="Events in next 7 days")
    upcoming_30_days: int = Field(..., description="Events in next 30 days")


class CalendarResponse(BaseModel):
    """Schema for calendar response."""

    events: list[CalendarEvent] = Field(
        default_factory=list, description="List of calendar events"
    )
    summary: CalendarSummary = Field(..., description="Summary statistics")

"""Pydantic schemas for Vehicle Reminder operations."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReminderCreate(BaseModel):
    """Schema for creating a vehicle reminder."""

    title: str = Field(..., min_length=1, max_length=200)
    reminder_type: Literal["date", "mileage", "both", "smart"]
    due_date: date | None = None
    due_mileage: int | None = Field(None, gt=0)
    notes: str | None = None
    line_item_id: int | None = None

    @model_validator(mode="after")
    def validate_fields_for_type(self) -> "ReminderCreate":
        """Ensure required fields are present based on reminder type."""
        if self.reminder_type in ("date", "both", "smart") and not self.due_date:
            raise ValueError("due_date required for this reminder type")
        if self.reminder_type in ("mileage", "both", "smart") and not self.due_mileage:
            raise ValueError("due_mileage required for this reminder type")
        return self


class ReminderUpdate(BaseModel):
    """Schema for updating a vehicle reminder.

    Status is NOT here — use /done or /dismiss endpoints.
    Validation is lenient (fields may be absent). The route handler merges
    this patch onto the existing reminder and validates the final state.
    """

    title: str | None = Field(None, min_length=1, max_length=200)
    reminder_type: Literal["date", "mileage", "both", "smart"] | None = None
    due_date: date | None = None
    due_mileage: int | None = Field(None, gt=0)
    notes: str | None = None


class ReminderResponse(BaseModel):
    """Schema for reminder response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    vin: str
    line_item_id: int | None
    title: str
    reminder_type: str
    due_date: date | None
    due_mileage: int | None
    status: str
    notes: str | None
    estimated_due_date: date | None = None
    last_notified_at: datetime | None
    created_at: datetime
    updated_at: datetime

"""Reminder schemas for MyGarage API."""

from datetime import date as date_type
from datetime import datetime as datetime_type

from pydantic import BaseModel, Field


class ReminderBase(BaseModel):
    """Base reminder schema."""

    description: str = Field(..., max_length=200)
    due_date: date_type | None = None
    due_mileage: int | None = Field(None, ge=0)
    is_recurring: bool = False
    recurrence_days: int | None = Field(None, ge=1)
    recurrence_miles: int | None = Field(None, ge=1)
    notes: str | None = None


class ReminderCreate(ReminderBase):
    """Schema for creating a reminder."""

    vin: str = Field(..., max_length=17)


class ReminderUpdate(BaseModel):
    """Schema for updating a reminder."""

    description: str | None = Field(None, max_length=200)
    due_date: date_type | None = None
    due_mileage: int | None = Field(None, ge=0)
    is_recurring: bool | None = None
    recurrence_days: int | None = Field(None, ge=1)
    recurrence_miles: int | None = Field(None, ge=1)
    is_completed: bool | None = None
    notes: str | None = None


class ReminderResponse(ReminderBase):
    """Schema for reminder response."""

    id: int
    vin: str
    is_completed: bool
    completed_at: datetime_type | None = None
    created_at: datetime_type

    class Config:
        """Pydantic config."""

        from_attributes = True


class ReminderListResponse(BaseModel):
    """Schema for list of reminders."""

    reminders: list[ReminderResponse]
    total: int
    active: int
    completed: int

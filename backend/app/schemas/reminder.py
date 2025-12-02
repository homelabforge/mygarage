"""Reminder schemas for MyGarage API."""

from datetime import date as date_type, datetime as datetime_type
from typing import Optional

from pydantic import BaseModel, Field


class ReminderBase(BaseModel):
    """Base reminder schema."""

    description: str = Field(..., max_length=200)
    due_date: Optional[date_type] = None
    due_mileage: Optional[int] = Field(None, ge=0)
    is_recurring: bool = False
    recurrence_days: Optional[int] = Field(None, ge=1)
    recurrence_miles: Optional[int] = Field(None, ge=1)
    notes: Optional[str] = None


class ReminderCreate(ReminderBase):
    """Schema for creating a reminder."""

    vin: str = Field(..., max_length=17)


class ReminderUpdate(BaseModel):
    """Schema for updating a reminder."""

    description: Optional[str] = Field(None, max_length=200)
    due_date: Optional[date_type] = None
    due_mileage: Optional[int] = Field(None, ge=0)
    is_recurring: Optional[bool] = None
    recurrence_days: Optional[int] = Field(None, ge=1)
    recurrence_miles: Optional[int] = Field(None, ge=1)
    is_completed: Optional[bool] = None
    notes: Optional[str] = None


class ReminderResponse(ReminderBase):
    """Schema for reminder response."""

    id: int
    vin: str
    is_completed: bool
    completed_at: Optional[datetime_type] = None
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

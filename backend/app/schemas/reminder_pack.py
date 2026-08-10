"""Pydantic schemas for built-in reminder packs."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ReminderPackItem(BaseModel):
    """A single reminder template inside a pack."""

    title: str
    reminder_type: str
    due_mileage_km: Decimal | None = None
    due_date_offset_days: int | None = None
    due_hours: Decimal | None = None
    notes: str | None = None


class ReminderPackSummary(BaseModel):
    """Pack metadata returned by list endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    reminder_count: int = Field(..., description="Number of reminders created when applied")
    vehicle_types: list[str] = Field(
        default_factory=list,
        description="Applicable vehicle types; empty means all types",
    )


class ReminderPackDetail(BaseModel):
    """Full pack definition including reminder templates."""

    id: str
    name: str
    description: str
    reminders: list[ReminderPackItem]
    vehicle_types: list[str] = Field(
        default_factory=list,
        description="Applicable vehicle types; empty means all types",
    )


class ApplyReminderPackRequest(BaseModel):
    """Request body for applying a reminder pack to a vehicle."""

    pack_id: str = Field(..., min_length=1, max_length=100)

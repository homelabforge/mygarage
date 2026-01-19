"""Pydantic schemas for Maintenance Schedule operations."""

from typing import Optional, Literal
from datetime import date as date_type, datetime
from pydantic import BaseModel, Field, field_validator

# Component category types
ComponentCategory = Literal[
    "Engine",
    "Transmission",
    "Brakes",
    "Tires",
    "Electrical",
    "HVAC",
    "Fluids",
    "Suspension",
    "Body/Exterior",
    "Interior",
    "Exhaust",
    "Fuel System",
    "Other",
]

# Item type
ItemType = Literal["service", "inspection"]

# Source type
SourceType = Literal["template", "custom", "migrated_reminder"]

# Status type
StatusType = Literal["never_performed", "overdue", "due_soon", "on_track"]


class MaintenanceScheduleItemBase(BaseModel):
    """Base maintenance schedule item schema."""

    name: str = Field(
        ..., description="Maintenance item name", min_length=1, max_length=100
    )
    component_category: ComponentCategory = Field(..., description="Component category")
    item_type: ItemType = Field(..., description="Item type (service or inspection)")
    interval_months: Optional[int] = Field(None, description="Interval in months", ge=1)
    interval_miles: Optional[int] = Field(None, description="Interval in miles", ge=100)

    @field_validator("component_category")
    @classmethod
    def validate_component_category(cls, v: str) -> str:
        """Validate component category."""
        valid_categories = [
            "Engine",
            "Transmission",
            "Brakes",
            "Tires",
            "Electrical",
            "HVAC",
            "Fluids",
            "Suspension",
            "Body/Exterior",
            "Interior",
            "Exhaust",
            "Fuel System",
            "Other",
        ]
        if v not in valid_categories:
            raise ValueError(
                f"Component category must be one of: {', '.join(valid_categories)}"
            )
        return v

    @field_validator("item_type")
    @classmethod
    def validate_item_type(cls, v: str) -> str:
        """Validate item type."""
        valid_types = ["service", "inspection"]
        if v not in valid_types:
            raise ValueError(f"Item type must be one of: {', '.join(valid_types)}")
        return v


class MaintenanceScheduleItemCreate(MaintenanceScheduleItemBase):
    """Schema for creating a new maintenance schedule item."""

    vin: str = Field(..., description="Vehicle VIN", min_length=17, max_length=17)
    source: SourceType = Field(default="custom", description="Source of item")
    template_item_id: Optional[str] = Field(
        None, description="Template item ID if from template"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vin": "ML32A5HJ9KH009478",
                    "name": "Engine Oil & Filter Change",
                    "component_category": "Engine",
                    "item_type": "service",
                    "interval_months": 6,
                    "interval_miles": 7500,
                    "source": "custom",
                }
            ]
        }
    }


class MaintenanceScheduleItemUpdate(BaseModel):
    """Schema for updating a maintenance schedule item."""

    name: Optional[str] = Field(
        None, description="Maintenance item name", min_length=1, max_length=100
    )
    component_category: Optional[ComponentCategory] = Field(
        None, description="Component category"
    )
    item_type: Optional[ItemType] = Field(
        None, description="Item type (service or inspection)"
    )
    interval_months: Optional[int] = Field(None, description="Interval in months", ge=1)
    interval_miles: Optional[int] = Field(None, description="Interval in miles", ge=100)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "interval_months": 3,
                    "interval_miles": 5000,
                }
            ]
        }
    }


class MaintenanceScheduleItemResponse(MaintenanceScheduleItemBase):
    """Schema for maintenance schedule item response."""

    id: int
    vin: str
    source: str
    template_item_id: Optional[str] = None
    last_performed_date: Optional[date_type] = None
    last_performed_mileage: Optional[int] = None
    last_service_line_item_id: Optional[int] = None
    next_due_date: Optional[date_type] = Field(
        None, description="Calculated next due date"
    )
    next_due_mileage: Optional[int] = Field(
        None, description="Calculated next due mileage"
    )
    status: StatusType = Field(description="Current status")
    days_until_due: Optional[int] = Field(None, description="Days until due")
    miles_until_due: Optional[int] = Field(None, description="Miles until due")
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "vin": "ML32A5HJ9KH009478",
                    "name": "Engine Oil & Filter Change",
                    "component_category": "Engine",
                    "item_type": "service",
                    "interval_months": 6,
                    "interval_miles": 7500,
                    "source": "template",
                    "template_item_id": "oil_change",
                    "last_performed_date": "2025-09-19",
                    "last_performed_mileage": 84717,
                    "last_service_line_item_id": 42,
                    "next_due_date": "2026-03-19",
                    "next_due_mileage": 92217,
                    "status": "due_soon",
                    "days_until_due": 63,
                    "miles_until_due": 217,
                    "created_at": "2025-01-01T00:00:00",
                    "updated_at": None,
                }
            ]
        },
    }


class MaintenanceScheduleListResponse(BaseModel):
    """Schema for maintenance schedule list response."""

    items: list[MaintenanceScheduleItemResponse]
    total: int
    due_soon_count: int = Field(description="Number of items due soon")
    overdue_count: int = Field(description="Number of overdue items")
    on_track_count: int = Field(description="Number of items on track")
    never_performed_count: int = Field(description="Number of never-performed items")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "items": [],
                    "total": 16,
                    "due_soon_count": 3,
                    "overdue_count": 0,
                    "on_track_count": 13,
                    "never_performed_count": 0,
                }
            ]
        }
    }


class ApplyTemplateRequest(BaseModel):
    """Schema for applying a maintenance template."""

    template_source: str = Field(
        ..., description="Template source identifier (e.g., 'toyota_standard')"
    )
    initial_date: Optional[date_type] = Field(
        None, description="Initial 'last performed' date for all items"
    )
    initial_mileage: Optional[int] = Field(
        None, description="Initial 'last performed' mileage for all items"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "template_source": "toyota_standard",
                    "initial_date": "2025-01-01",
                    "initial_mileage": 75000,
                }
            ]
        }
    }


class ApplyTemplateResponse(BaseModel):
    """Schema for apply template response."""

    items_created: int = Field(description="Number of schedule items created")
    items_skipped: int = Field(description="Number of items skipped (already exist)")
    message: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "items_created": 16,
                    "items_skipped": 0,
                    "message": "Successfully applied template 'toyota_standard' with 16 maintenance items",
                }
            ]
        }
    }

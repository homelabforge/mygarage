"""Pydantic schemas for Service Visit operations."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.reminder import ReminderCreate  # noqa: F401 — used in type annotations

# Service category type (same as existing)
ServiceCategory = Literal["Maintenance", "Inspection", "Collision", "Upgrades", "Detailing"]

# Inspection result types
InspectionResult = Literal["passed", "failed", "needs_attention"]
InspectionSeverity = Literal["green", "yellow", "red"]


class ServiceLineItemBase(BaseModel):
    """Base service line item schema."""

    description: str = Field(..., description="Service description", min_length=1, max_length=200)
    category: ServiceCategory | None = Field(None, description="Service category")
    cost: Decimal | None = Field(None, description="Cost for this line item", ge=0)
    notes: str | None = Field(None, description="Additional notes", max_length=5000)
    is_inspection: bool = Field(default=False, description="Is this an inspection item")
    inspection_result: InspectionResult | None = Field(
        None, description="Inspection result (if inspection)"
    )
    inspection_severity: InspectionSeverity | None = Field(
        None, description="Inspection severity (if inspection)"
    )
    triggered_by_inspection_id: int | None = Field(
        None, description="ID of inspection that triggered this repair"
    )

    @field_validator("inspection_result")
    @classmethod
    def validate_inspection_result(cls, v: str | None) -> str | None:
        """Validate inspection result."""
        if v is None:
            return v
        valid_values = ["passed", "failed", "needs_attention"]
        if v not in valid_values:
            raise ValueError(f"inspection_result must be one of: {', '.join(valid_values)}")
        return v

    @field_validator("inspection_severity")
    @classmethod
    def validate_inspection_severity(cls, v: str | None) -> str | None:
        """Validate inspection severity."""
        if v is None:
            return v
        valid_values = ["green", "yellow", "red"]
        if v not in valid_values:
            raise ValueError(f"inspection_severity must be one of: {', '.join(valid_values)}")
        return v


class ServiceLineItemCreate(ServiceLineItemBase):
    """Schema for creating a service line item."""

    reminder: ReminderCreate | None = Field(
        None, description="Optional reminder to create after flush"
    )
    temp_id: int | None = Field(None, description="Transient client temp ID; not persisted to DB")

    @model_validator(mode="after")
    def validate_temp_id(self) -> ServiceLineItemCreate:
        """temp_id must be a negative integer if provided."""
        if self.temp_id is not None and self.temp_id >= 0:
            raise ValueError("temp_id must be a negative integer")
        return self

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "description": "Engine Oil & Filter Change",
                    "cost": 112.23,
                    "notes": "Used SAE 0W-20 synthetic",
                    "is_inspection": False,
                    "category": "Maintenance",
                }
            ]
        }
    }


class ServiceLineItemUpdate(BaseModel):
    """Line item shape for diff-based visit updates.

    temp_id: negative int assigned by client for new items so other new items
    can reference them via triggered_by_inspection_id before flush.
    """

    id: int | None = Field(None, description="Existing item id; omit for new items")
    temp_id: int | None = Field(None, description="Client temp ID; must be negative; not persisted")
    description: str = Field(..., min_length=1, max_length=200)
    category: ServiceCategory | None = None
    cost: Decimal | None = Field(None, ge=0)
    notes: str | None = Field(None, max_length=5000)
    is_inspection: bool = False
    inspection_result: InspectionResult | None = None
    inspection_severity: InspectionSeverity | None = None
    triggered_by_inspection_id: int | None = None
    reminder: ReminderCreate | None = None

    @model_validator(mode="after")
    def validate_temp_id(self) -> ServiceLineItemUpdate:
        """temp_id must be a negative integer if provided."""
        if self.temp_id is not None and self.temp_id >= 0:
            raise ValueError("temp_id must be a negative integer")
        return self


class ServiceLineItemResponse(ServiceLineItemBase):
    """Schema for service line item response."""

    id: int
    visit_id: int
    created_at: datetime
    is_failed_inspection: bool = Field(
        default=False, description="Whether this is a failed inspection"
    )
    needs_followup: bool = Field(
        default=False, description="Whether this inspection needs followup"
    )

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "visit_id": 1,
                    "description": "Engine Oil & Filter Change",
                    "cost": "112.23",
                    "notes": "Used SAE 0W-20 synthetic",
                    "is_inspection": False,
                    "inspection_result": None,
                    "inspection_severity": None,
                    "category": "Maintenance",
                    "triggered_by_inspection_id": None,
                    "created_at": "2026-01-15T10:30:00",
                    "is_failed_inspection": False,
                    "needs_followup": False,
                }
            ]
        },
    }


class ServiceVisitBase(BaseModel):
    """Base service visit schema."""

    date: date_type = Field(..., description="Visit date")
    mileage: int | None = Field(None, description="Odometer reading", ge=0)
    notes: str | None = Field(None, description="Visit notes", max_length=5000)
    service_category: ServiceCategory | None = Field(None, description="Primary service category")
    insurance_claim_number: str | None = Field(
        None, description="Insurance claim number", max_length=50
    )
    vendor_id: int | None = Field(None, description="Vendor ID")
    tax_amount: Decimal | None = Field(None, description="Sales tax", ge=0)
    shop_supplies: Decimal | None = Field(None, description="Shop supplies/environmental fee", ge=0)
    misc_fees: Decimal | None = Field(None, description="Miscellaneous fees (disposal, etc.)", ge=0)

    @field_validator("service_category")
    @classmethod
    def validate_service_category(cls, v: str | None) -> str | None:
        """Validate service category."""
        if v is None:
            return v
        valid_types = [
            "Maintenance",
            "Inspection",
            "Collision",
            "Upgrades",
            "Detailing",
        ]
        if v not in valid_types:
            raise ValueError(f"Service category must be one of: {', '.join(valid_types)}")
        return v


class ServiceVisitCreate(ServiceVisitBase):
    """Schema for creating a new service visit."""

    line_items: list[ServiceLineItemCreate] = Field(
        ..., description="Services performed during this visit", min_length=1
    )
    total_cost: Decimal | None = Field(
        None, description="Override total cost (otherwise calculated from line items)"
    )

    @model_validator(mode="after")
    def validate_line_item_temp_ids(self) -> ServiceVisitCreate:
        """Enforce temp_id payload contract."""
        if not self.line_items:
            return self
        temp_ids = [i.temp_id for i in self.line_items if i.temp_id is not None]
        if len(temp_ids) != len(set(temp_ids)):
            raise ValueError("temp_id values must be unique within a payload")
        temp_id_set = set(temp_ids)
        for item in self.line_items:
            if item.triggered_by_inspection_id is not None:
                ref = item.triggered_by_inspection_id
                if ref < 0 and ref not in temp_id_set:
                    raise ValueError(f"triggered_by_inspection_id {ref} references unknown temp_id")
        return self

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "date": "2026-01-15",
                    "mileage": 92500,
                    "service_category": "Maintenance",
                    "vendor_id": 1,
                    "notes": "Regular maintenance visit",
                    "line_items": [
                        {
                            "description": "Engine Oil & Filter Change",
                            "cost": 112.23,
                            "category": "Maintenance",
                        },
                        {
                            "description": "Tire Rotation",
                            "cost": 0,
                            "notes": "Included with oil change",
                            "category": "Maintenance",
                        },
                    ],
                }
            ]
        }
    }


class ServiceVisitUpdate(BaseModel):
    """Schema for updating an existing service visit."""

    date: date_type | None = Field(None, description="Visit date")
    mileage: int | None = Field(None, description="Odometer reading", ge=0)
    notes: str | None = Field(None, description="Visit notes", max_length=5000)
    service_category: ServiceCategory | None = Field(None, description="Primary service category")
    insurance_claim_number: str | None = Field(
        None, description="Insurance claim number", max_length=50
    )
    vendor_id: int | None = Field(None, description="Vendor ID")
    total_cost: Decimal | None = Field(None, description="Override total cost")
    tax_amount: Decimal | None = Field(None, description="Sales tax", ge=0)
    shop_supplies: Decimal | None = Field(None, description="Shop supplies/environmental fee", ge=0)
    misc_fees: Decimal | None = Field(None, description="Miscellaneous fees (disposal, etc.)", ge=0)
    line_items: list[ServiceLineItemUpdate] | None = Field(
        None, description="Diff-based line items (if provided)"
    )

    @model_validator(mode="after")
    def validate_line_item_temp_ids(self) -> ServiceVisitUpdate:
        """Enforce temp_id payload contract."""
        if not self.line_items:
            return self
        temp_ids = [i.temp_id for i in self.line_items if i.temp_id is not None]
        if len(temp_ids) != len(set(temp_ids)):
            raise ValueError("temp_id values must be unique within a payload")
        temp_id_set = set(temp_ids)
        existing_ids = {i.id for i in self.line_items if i.id}
        for item in self.line_items:
            if item.triggered_by_inspection_id is not None:
                ref = item.triggered_by_inspection_id
                if ref < 0 and ref not in temp_id_set:
                    raise ValueError(f"triggered_by_inspection_id {ref} references unknown temp_id")
                if ref > 0 and item.id and ref not in existing_ids:
                    # Positive ref to a real ID that's not in this payload is fine —
                    # it could be an existing DB ID not being edited in this payload.
                    pass
        return self

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "notes": "Updated notes",
                    "total_cost": 150.00,
                }
            ]
        }
    }


class VendorSummary(BaseModel):
    """Brief vendor info for embedding in visit response."""

    id: int
    name: str
    city: str | None = None
    state: str | None = None

    model_config = {"from_attributes": True}


class ServiceVisitResponse(ServiceVisitBase):
    """Schema for service visit response."""

    id: int
    vin: str
    total_cost: Decimal | None = None
    subtotal: Decimal = Field(description="Sum of line item costs (before tax/fees)")
    calculated_total_cost: Decimal = Field(description="Total including line items + tax + fees")
    line_item_count: int = Field(description="Number of line items")
    has_failed_inspections: bool = Field(description="Whether any inspections failed")
    created_at: datetime
    updated_at: datetime | None = None
    line_items: list[ServiceLineItemResponse] = []
    vendor: VendorSummary | None = None

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "vin": "ML32A5HJ9KH009478",
                    "vendor_id": 1,
                    "date": "2026-01-15",
                    "mileage": 92500,
                    "total_cost": "112.23",
                    "calculated_total_cost": "112.23",
                    "notes": "Regular maintenance visit",
                    "service_category": "Maintenance",
                    "insurance_claim_number": None,
                    "line_item_count": 2,
                    "has_failed_inspections": False,
                    "created_at": "2026-01-15T10:30:00",
                    "updated_at": None,
                    "line_items": [],
                    "vendor": {
                        "id": 1,
                        "name": "Mavis Tires & Brakes",
                        "city": "Carthage",
                        "state": "TX",
                    },
                }
            ]
        },
    }


class ServiceVisitListResponse(BaseModel):
    """Schema for service visit list response."""

    visits: list[ServiceVisitResponse]
    total: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "visits": [
                        {
                            "id": 1,
                            "vin": "ML32A5HJ9KH009478",
                            "date": "2026-01-15",
                            "total_cost": "112.23",
                            "service_category": "Maintenance",
                            "line_item_count": 2,
                            "created_at": "2026-01-15T10:30:00",
                        }
                    ],
                    "total": 1,
                }
            ]
        }
    }

"""Pydantic schemas for Service Visit operations."""

from typing import Optional, Literal
from datetime import date as date_type, datetime
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator

# Service category type (same as existing)
ServiceCategory = Literal[
    "Maintenance", "Inspection", "Collision", "Upgrades", "Detailing"
]

# Inspection result types
InspectionResult = Literal["passed", "failed", "needs_attention"]
InspectionSeverity = Literal["green", "yellow", "red"]


class ServiceLineItemBase(BaseModel):
    """Base service line item schema."""

    description: str = Field(
        ..., description="Service description", min_length=1, max_length=200
    )
    cost: Optional[Decimal] = Field(None, description="Cost for this line item", ge=0)
    notes: Optional[str] = Field(None, description="Additional notes", max_length=5000)
    is_inspection: bool = Field(default=False, description="Is this an inspection item")
    inspection_result: Optional[InspectionResult] = Field(
        None, description="Inspection result (if inspection)"
    )
    inspection_severity: Optional[InspectionSeverity] = Field(
        None, description="Inspection severity (if inspection)"
    )
    schedule_item_id: Optional[int] = Field(
        None, description="Link to maintenance schedule item"
    )
    triggered_by_inspection_id: Optional[int] = Field(
        None, description="ID of inspection that triggered this repair"
    )

    @field_validator("inspection_result")
    @classmethod
    def validate_inspection_result(cls, v: Optional[str]) -> Optional[str]:
        """Validate inspection result."""
        if v is None:
            return v
        valid_values = ["passed", "failed", "needs_attention"]
        if v not in valid_values:
            raise ValueError(
                f"inspection_result must be one of: {', '.join(valid_values)}"
            )
        return v

    @field_validator("inspection_severity")
    @classmethod
    def validate_inspection_severity(cls, v: Optional[str]) -> Optional[str]:
        """Validate inspection severity."""
        if v is None:
            return v
        valid_values = ["green", "yellow", "red"]
        if v not in valid_values:
            raise ValueError(
                f"inspection_severity must be one of: {', '.join(valid_values)}"
            )
        return v


class ServiceLineItemCreate(ServiceLineItemBase):
    """Schema for creating a service line item."""

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "description": "Engine Oil & Filter Change",
                    "cost": 112.23,
                    "notes": "Used SAE 0W-20 synthetic",
                    "is_inspection": False,
                    "schedule_item_id": 5,
                }
            ]
        }
    }


class ServiceLineItemUpdate(BaseModel):
    """Schema for updating a service line item."""

    description: Optional[str] = Field(
        None, description="Service description", min_length=1, max_length=200
    )
    cost: Optional[Decimal] = Field(None, description="Cost for this line item", ge=0)
    notes: Optional[str] = Field(None, description="Additional notes", max_length=5000)
    is_inspection: Optional[bool] = Field(
        None, description="Is this an inspection item"
    )
    inspection_result: Optional[InspectionResult] = Field(
        None, description="Inspection result (if inspection)"
    )
    inspection_severity: Optional[InspectionSeverity] = Field(
        None, description="Inspection severity (if inspection)"
    )
    schedule_item_id: Optional[int] = Field(
        None, description="Link to maintenance schedule item"
    )


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
                    "schedule_item_id": 5,
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
    mileage: Optional[int] = Field(None, description="Odometer reading", ge=0)
    notes: Optional[str] = Field(None, description="Visit notes", max_length=5000)
    service_category: Optional[ServiceCategory] = Field(
        None, description="Primary service category"
    )
    insurance_claim_number: Optional[str] = Field(
        None, description="Insurance claim number", max_length=50
    )
    vendor_id: Optional[int] = Field(None, description="Vendor ID")
    tax_amount: Optional[Decimal] = Field(None, description="Sales tax", ge=0)
    shop_supplies: Optional[Decimal] = Field(
        None, description="Shop supplies/environmental fee", ge=0
    )
    misc_fees: Optional[Decimal] = Field(
        None, description="Miscellaneous fees (disposal, etc.)", ge=0
    )

    @field_validator("service_category")
    @classmethod
    def validate_service_category(cls, v: Optional[str]) -> Optional[str]:
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
            raise ValueError(
                f"Service category must be one of: {', '.join(valid_types)}"
            )
        return v


class ServiceVisitCreate(ServiceVisitBase):
    """Schema for creating a new service visit."""

    line_items: list[ServiceLineItemCreate] = Field(
        ..., description="Services performed during this visit", min_length=1
    )
    total_cost: Optional[Decimal] = Field(
        None, description="Override total cost (otherwise calculated from line items)"
    )

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
                            "schedule_item_id": 5,
                        },
                        {
                            "description": "Tire Rotation",
                            "cost": 0,
                            "notes": "Included with oil change",
                            "schedule_item_id": 8,
                        },
                    ],
                }
            ]
        }
    }


class ServiceVisitUpdate(BaseModel):
    """Schema for updating an existing service visit."""

    date: Optional[date_type] = Field(None, description="Visit date")
    mileage: Optional[int] = Field(None, description="Odometer reading", ge=0)
    notes: Optional[str] = Field(None, description="Visit notes", max_length=5000)
    service_category: Optional[ServiceCategory] = Field(
        None, description="Primary service category"
    )
    insurance_claim_number: Optional[str] = Field(
        None, description="Insurance claim number", max_length=50
    )
    vendor_id: Optional[int] = Field(None, description="Vendor ID")
    total_cost: Optional[Decimal] = Field(None, description="Override total cost")
    tax_amount: Optional[Decimal] = Field(None, description="Sales tax", ge=0)
    shop_supplies: Optional[Decimal] = Field(
        None, description="Shop supplies/environmental fee", ge=0
    )
    misc_fees: Optional[Decimal] = Field(
        None, description="Miscellaneous fees (disposal, etc.)", ge=0
    )
    line_items: Optional[list[ServiceLineItemCreate]] = Field(
        None, description="Replace all line items (if provided)"
    )

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
    city: Optional[str] = None
    state: Optional[str] = None

    model_config = {"from_attributes": True}


class ServiceVisitResponse(ServiceVisitBase):
    """Schema for service visit response."""

    id: int
    vin: str
    total_cost: Optional[Decimal] = None
    subtotal: Decimal = Field(description="Sum of line item costs (before tax/fees)")
    calculated_total_cost: Decimal = Field(
        description="Total including line items + tax + fees"
    )
    line_item_count: int = Field(description="Number of line items")
    has_failed_inspections: bool = Field(description="Whether any inspections failed")
    created_at: datetime
    updated_at: Optional[datetime] = None
    line_items: list[ServiceLineItemResponse] = []
    vendor: Optional[VendorSummary] = None

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

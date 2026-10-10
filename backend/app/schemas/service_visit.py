"""Pydantic schemas for Service Visit operations."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, field_validator, model_validator

from app.schemas._money import OptionalMoney
from app.schemas._nullability import reject_null
from app.schemas.maintenance import validate_maintenance_type
from app.schemas.reminder import ReminderCreate  # noqa: F401 — used in type annotations
from app.schemas.supply import SupplyUsageInput, SupplyUsageResponse
from app.utils.lenient_vocab import LenientVocab, lenient_reader

# Service category type (same as existing)
ServiceCategory = Literal["Maintenance", "Inspection", "Collision", "Upgrades", "Detailing"]
# A line item's category has no CHECK (the visit's does), so its response reads
# an unknown one as null instead of 500ing the visit.
LenientServiceCategory = Annotated[
    ServiceCategory | None, BeforeValidator(lenient_reader(ServiceCategory)), LenientVocab(None)
]

# Inspection result types
InspectionResult = Literal["passed", "failed", "needs_attention"]
InspectionSeverity = Literal["green", "yellow", "red"]


class ServiceLineItemBase(BaseModel):
    """Base service line item schema."""

    description: str = Field(..., description="Service description", min_length=1, max_length=200)
    category: ServiceCategory | None = Field(None, description="Service category")
    maintenance_type: str | None = Field(
        None,
        description=(
            "Canonical maintenance type code; classified from the description when omitted"
        ),
        max_length=50,
    )
    cost: OptionalMoney = Field(None, description="Cost for this line item")
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
    supplies_used: list[SupplyUsageInput] = Field(
        default_factory=list, description="Supplies consumed by this line item"
    )

    # Here and not on the base: the response shares it, and a legacy row with a
    # free-text type ("Oil Change") would 500 the visit.
    @field_validator("maintenance_type")
    @classmethod
    def validate_maintenance_type_code(cls, v: str | None) -> str | None:
        """A stored code is lowercase snake_case."""
        return validate_maintenance_type(v)

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
    maintenance_type: str | None = Field(None, max_length=50)
    cost: OptionalMoney = None
    notes: str | None = Field(None, max_length=5000)
    is_inspection: bool = False
    inspection_result: InspectionResult | None = None
    inspection_severity: InspectionSeverity | None = None
    triggered_by_inspection_id: int | None = None
    reminder: ReminderCreate | None = None
    supplies_used: list[SupplyUsageInput] = Field(
        default_factory=list,
        description=(
            "Supplies consumed by this line item. Omit to keep the current ones; "
            "send [] to remove them."
        ),
    )

    @field_validator("maintenance_type")
    @classmethod
    def validate_maintenance_type_code(cls, v: str | None) -> str | None:
        """A stored code is lowercase snake_case."""
        return validate_maintenance_type(v)

    @model_validator(mode="after")
    def validate_temp_id(self) -> ServiceLineItemUpdate:
        """temp_id must be a negative integer if provided."""
        if self.temp_id is not None and self.temp_id >= 0:
            raise ValueError("temp_id must be a negative integer")
        return self


class ServiceLineItemResponse(ServiceLineItemBase):
    """Schema for service line item response."""

    # Money without the input bounds, so a stored amount past today's rules
    # still reads instead of 500ing (test_response_contract).
    cost: Decimal | None = Field(None, description="Cost for this line item")
    # Text without the input rules, so a stored string past today's limits
    # still reads instead of 500ing (test_response_contract).
    description: str = Field(..., description="Service description")
    maintenance_type: str | None = Field(
        None,
        description=(
            "Canonical maintenance type code; classified from the description when omitted"
        ),
    )
    notes: str | None = Field(None, description="Additional notes")
    # A category we don't know reads as null instead of 500ing the visit.
    category: LenientServiceCategory = Field(None, description="Service category")
    id: int
    visit_id: int
    created_at: datetime
    is_failed_inspection: bool = Field(
        default=False, description="Whether this is a failed inspection"
    )
    needs_followup: bool = Field(
        default=False, description="Whether this inspection needs followup"
    )
    supply_usages: list[SupplyUsageResponse] = Field(default_factory=list)

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
    odometer_km: Decimal | None = Field(
        None, description="Odometer reading in kilometers", ge=0, le=99999999.99
    )
    engine_hours: Decimal | None = Field(
        None,
        description=(
            "Engine-hours reading at this service visit (hour-metered vehicles). "
            "Dimensionless, no unit conversion. Auto-syncs to hours history."
        ),
        ge=0,
        le=9999999.9,
    )
    notes: str | None = Field(None, description="Visit notes", max_length=5000)
    service_category: ServiceCategory | None = Field(None, description="Primary service category")
    insurance_claim_number: str | None = Field(
        None, description="Insurance claim number", max_length=50
    )
    vendor_id: int | None = Field(None, description="Vendor ID")
    tax_amount: OptionalMoney = Field(None, description="Sales tax")
    shop_supplies: OptionalMoney = Field(None, description="Shop supplies/environmental fee")
    misc_fees: OptionalMoney = Field(None, description="Miscellaneous fees (disposal, etc.)")

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
    total_cost: OptionalMoney = Field(
        None,
        description="Ignored: the server always computes the total from line items, "
        "supplies, tax and fees. Accepted so existing clients don't 422.",
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
                    "odometer_km": 148864,
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
    odometer_km: Decimal | None = Field(
        None, description="Odometer reading in kilometers", ge=0, le=99999999.99
    )
    engine_hours: Decimal | None = Field(
        None,
        description="Engine-hours reading at this service visit (hour-metered vehicles)",
        ge=0,
        le=9999999.9,
    )
    notes: str | None = Field(None, description="Visit notes", max_length=5000)
    service_category: ServiceCategory | None = Field(None, description="Primary service category")
    insurance_claim_number: str | None = Field(
        None, description="Insurance claim number", max_length=50
    )
    vendor_id: int | None = Field(None, description="Vendor ID")
    total_cost: OptionalMoney = Field(
        None,
        description="Ignored: the server always computes the total from line items, "
        "supplies, tax and fees. Accepted so existing clients don't 422.",
    )
    tax_amount: OptionalMoney = Field(None, description="Sales tax")
    shop_supplies: OptionalMoney = Field(None, description="Shop supplies/environmental fee")
    misc_fees: OptionalMoney = Field(None, description="Miscellaneous fees (disposal, etc.)")
    line_items: list[ServiceLineItemUpdate] | None = Field(
        None, description="Diff-based line items (if provided)"
    )

    # NOT NULL column: omitted keeps the stored value, null is a 422.
    _no_null = reject_null("date")

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
                    "tax_amount": 8.50,
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

    # Numbers without the input bounds, so a stored value past today's rules
    # still reads instead of 500ing (test_response_contract).
    odometer_km: Decimal | None = Field(None, description="Odometer reading in kilometers")
    engine_hours: Decimal | None = Field(
        None,
        description=(
            "Engine-hours reading at this service visit (hour-metered vehicles). "
            "Dimensionless, no unit conversion. Auto-syncs to hours history."
        ),
    )
    tax_amount: Decimal | None = Field(None, description="Sales tax")
    shop_supplies: Decimal | None = Field(None, description="Shop supplies/environmental fee")
    misc_fees: Decimal | None = Field(None, description="Miscellaneous fees (disposal, etc.)")
    # Text without the input rules, so a stored string past today's limits
    # still reads instead of 500ing (test_response_contract).
    notes: str | None = Field(None, description="Visit notes")
    insurance_claim_number: str | None = Field(None, description="Insurance claim number")
    id: int
    vin: str
    total_cost: Decimal | None = None
    subtotal: Decimal = Field(description="Sum of line item costs (before tax/fees)")
    calculated_total_cost: Decimal = Field(description="Total including line items + tax + fees")
    parts_supplies_cost: Decimal = Field(
        default=Decimal(0), description="Σ supply usage cost snapshots across line items"
    )
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
                    "odometer_km": 148864,
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

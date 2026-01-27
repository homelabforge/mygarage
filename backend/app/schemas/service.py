"""Pydantic schemas for Service Record operations."""

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Service category type
ServiceCategory = Literal["Maintenance", "Inspection", "Collision", "Upgrades", "Detailing"]

# Predefined service types grouped by category
SERVICE_TYPES_BY_CATEGORY = {
    "Maintenance": [
        "General Service",
        "Oil Change",
        "Tire Rotation",
        "Brake Service",
        "Transmission Service",
        "Coolant Flush",
        "Air Filter Replacement",
        "Cabin Filter Replacement",
        "Spark Plug Replacement",
        "Battery Replacement",
        "Wiper Blade Replacement",
        "Wheel Alignment",
        "Tire Replacement",
        "Suspension Service",
        "Exhaust Repair",
        "Fuel System Service",
        "Differential Service",
        "Transfer Case Service",
        "Engine Tune-Up",
        "Belt Replacement",
        "Hose Replacement",
        "AC Service",
        "AC Recharge",
    ],
    "Inspection": [
        "General Inspection",
        "Annual Safety Inspection",
        "Emissions Test",
        "Pre-Purchase Inspection",
        "Brake Inspection",
        "Tire Inspection",
        "Suspension Inspection",
        "Steering Inspection",
        "Electrical System Inspection",
        "Diagnostic Scan",
    ],
    "Collision": [
        "General Collision Repair",
        "Front End Repair",
        "Rear End Repair",
        "Side Impact Repair",
        "Frame Straightening",
        "Paint Repair",
        "Glass Replacement",
        "Bumper Repair",
        "Dent Removal",
        "Scratch Repair",
    ],
    "Detailing": [
        "Car Wash",
        "Hand Wash",
        "Wax",
        "Ceramic Coating",
        "Paint Correction",
        "Interior Detailing",
        "Exterior Detailing",
        "Full Detailing",
        "Engine Bay Cleaning",
        "Headlight Restoration",
        "Odor Removal",
        "Upholstery Cleaning",
    ],
    "Upgrades": [
        "General Upgrade",
        "Performance Upgrade",
        "Suspension Upgrade",
        "Exhaust Upgrade",
        "Intake Upgrade",
        "Audio System Upgrade",
        "Navigation System",
        "Backup Camera",
        "Remote Start",
        "Towing Package",
        "Lift Kit",
        "Wheels/Rims",
        "Lighting Upgrade",
        "Accessory Upgrade",
        "Window Tinting",
        "Tonneau Cover",
    ],
}

# All valid service types (flat list)
ALL_SERVICE_TYPES = [
    service_type
    for category_types in SERVICE_TYPES_BY_CATEGORY.values()
    for service_type in category_types
]


class ServiceRecordBase(BaseModel):
    """Base service record schema with common fields."""

    date: date_type = Field(..., description="Service date")
    mileage: int | None = Field(None, description="Odometer reading", ge=0)
    service_type: str = Field(
        ..., description="Specific service type", min_length=1, max_length=100
    )
    cost: Decimal | None = Field(None, description="Service cost", ge=0)
    notes: str | None = Field(None, description="Additional notes", max_length=5000)
    vendor_name: str | None = Field(None, description="Shop/vendor name", max_length=100)
    vendor_location: str | None = Field(None, description="Shop location", max_length=100)
    service_category: ServiceCategory | None = Field(None, description="Service category")
    insurance_claim: str | None = Field(None, description="Insurance claim number", max_length=50)

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

    @field_validator("service_type")
    @classmethod
    def validate_service_type(cls, v: str) -> str:
        """Validate service type against predefined list."""
        # Allow any string for now (frontend provides dropdown)
        # Could enforce strict validation here if desired
        return v


class ServiceRecordCreate(ServiceRecordBase):
    """Schema for creating a new service record."""

    vin: str = Field(..., description="Vehicle VIN", min_length=17, max_length=17)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vin": "ML32A5HJ9KH009478",
                    "date": "2025-01-15",
                    "mileage": 45000,
                    "service_type": "Oil Change",
                    "cost": 89.99,
                    "vendor_name": "Quick Lube",
                    "vendor_location": "123 Main St",
                    "service_category": "Maintenance",
                    "notes": "Used synthetic oil",
                }
            ]
        }
    }


class ServiceRecordUpdate(BaseModel):
    """Schema for updating an existing service record."""

    date: date_type | None = Field(None, description="Service date")
    mileage: int | None = Field(None, description="Odometer reading", ge=0)
    service_type: str | None = Field(
        None, description="Specific service type", min_length=1, max_length=100
    )
    cost: Decimal | None = Field(None, description="Service cost", ge=0)
    notes: str | None = Field(None, description="Additional notes", max_length=5000)
    vendor_name: str | None = Field(None, description="Shop/vendor name", max_length=100)
    vendor_location: str | None = Field(None, description="Shop location", max_length=100)
    service_category: ServiceCategory | None = Field(None, description="Service category")
    insurance_claim: str | None = Field(None, description="Insurance claim number", max_length=50)

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

    @field_validator("service_type")
    @classmethod
    def validate_service_type(cls, v: str | None) -> str | None:
        """Validate service type against predefined list."""
        if v is None:
            return v
        # Allow any string for now (frontend provides dropdown)
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "service_type": "Oil Change",
                    "cost": 95.00,
                    "notes": "Used synthetic oil",
                }
            ]
        }
    }


class ServiceRecordResponse(ServiceRecordBase):
    """Schema for service record response."""

    id: int
    vin: str
    created_at: datetime
    attachment_count: int = Field(default=0, description="Number of attachments")

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "vin": "ML32A5HJ9KH009478",
                    "date": "2025-01-15",
                    "mileage": 45000,
                    "service_type": "Oil Change",
                    "cost": "89.99",
                    "notes": "Used conventional oil",
                    "vendor_name": "Quick Lube",
                    "vendor_location": "123 Main St",
                    "service_category": "Maintenance",
                    "created_at": "2025-01-15T10:30:00",
                    "attachment_count": 0,
                }
            ]
        },
    }


class ServiceRecordListResponse(BaseModel):
    """Schema for service record list response."""

    records: list[ServiceRecordResponse]
    total: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "records": [
                        {
                            "id": 1,
                            "vin": "ML32A5HJ9KH009478",
                            "date": "2025-01-15",
                            "mileage": 45000,
                            "service_type": "Oil Change",
                            "cost": "89.99",
                            "service_category": "Maintenance",
                            "created_at": "2025-01-15T10:30:00",
                            "attachment_count": 0,
                        }
                    ],
                    "total": 1,
                }
            ]
        }
    }

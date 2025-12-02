"""Pydantic schemas for Service Record operations."""

from typing import Optional
from datetime import date as date_type, datetime
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator


class ServiceRecordBase(BaseModel):
    """Base service record schema with common fields."""

    date: date_type = Field(..., description="Service date")
    mileage: Optional[int] = Field(None, description="Odometer reading", ge=0)
    description: str = Field(..., description="Service description", min_length=1, max_length=200)
    cost: Optional[Decimal] = Field(None, description="Service cost", ge=0)
    notes: Optional[str] = Field(None, description="Additional notes", max_length=5000)
    vendor_name: Optional[str] = Field(None, description="Shop/vendor name", max_length=100)
    vendor_location: Optional[str] = Field(None, description="Shop location", max_length=100)
    service_type: Optional[str] = Field(None, description="Type of service")
    insurance_claim: Optional[str] = Field(None, description="Insurance claim number", max_length=50)

    @field_validator('service_type')
    @classmethod
    def validate_service_type(cls, v: Optional[str]) -> Optional[str]:
        """Validate service type."""
        if v is None:
            return v
        valid_types = ['Maintenance', 'Inspection', 'Collision', 'Upgrades']
        if v not in valid_types:
            raise ValueError(f'Service type must be one of: {", ".join(valid_types)}')
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
                    "description": "Oil change and tire rotation",
                    "cost": 89.99,
                    "vendor_name": "Quick Lube",
                    "vendor_location": "123 Main St",
                    "service_type": "Maintenance"
                }
            ]
        }
    }


class ServiceRecordUpdate(BaseModel):
    """Schema for updating an existing service record."""

    date: Optional[date_type] = Field(None, description="Service date")
    mileage: Optional[int] = Field(None, description="Odometer reading", ge=0)
    description: Optional[str] = Field(None, description="Service description", min_length=1, max_length=200)
    cost: Optional[Decimal] = Field(None, description="Service cost", ge=0)
    notes: Optional[str] = Field(None, description="Additional notes", max_length=5000)
    vendor_name: Optional[str] = Field(None, description="Shop/vendor name", max_length=100)
    vendor_location: Optional[str] = Field(None, description="Shop location", max_length=100)
    service_type: Optional[str] = Field(None, description="Type of service")
    insurance_claim: Optional[str] = Field(None, description="Insurance claim number", max_length=50)

    @field_validator('service_type')
    @classmethod
    def validate_service_type(cls, v: Optional[str]) -> Optional[str]:
        """Validate service type."""
        if v is None:
            return v
        valid_types = ['Maintenance', 'Inspection', 'Collision', 'Upgrades']
        if v not in valid_types:
            raise ValueError(f'Service type must be one of: {", ".join(valid_types)}')
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "cost": 95.00,
                    "notes": "Used synthetic oil"
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
                    "description": "Oil change and tire rotation",
                    "cost": "89.99",
                    "notes": "Used conventional oil",
                    "vendor_name": "Quick Lube",
                    "vendor_location": "123 Main St",
                    "service_type": "Maintenance",
                    "created_at": "2025-01-15T10:30:00"
                }
            ]
        }
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
                            "description": "Oil change",
                            "cost": "89.99",
                            "service_type": "Maintenance",
                            "created_at": "2025-01-15T10:30:00"
                        }
                    ],
                    "total": 1
                }
            ]
        }
    }

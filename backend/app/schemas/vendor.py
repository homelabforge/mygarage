"""Pydantic schemas for Vendor operations."""

from datetime import datetime

from pydantic import BaseModel, Field


class VendorBase(BaseModel):
    """Base vendor schema with common fields."""

    name: str = Field(..., description="Vendor/shop name", min_length=1, max_length=100)
    address: str | None = Field(None, description="Street address", max_length=500)
    city: str | None = Field(None, description="City", max_length=100)
    state: str | None = Field(None, description="State/province", max_length=50)
    zip_code: str | None = Field(None, description="ZIP/postal code", max_length=20)
    phone: str | None = Field(None, description="Phone number", max_length=20)


class VendorCreate(VendorBase):
    """Schema for creating a new vendor."""

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "Mavis Tires & Brakes",
                    "address": "603 W. Wellington ST",
                    "city": "Carthage",
                    "state": "TX",
                    "zip_code": "75633",
                    "phone": "(903) 693-9000",
                }
            ]
        }
    }


class VendorUpdate(BaseModel):
    """Schema for updating an existing vendor."""

    name: str | None = Field(None, description="Vendor/shop name", min_length=1, max_length=100)
    address: str | None = Field(None, description="Street address", max_length=500)
    city: str | None = Field(None, description="City", max_length=100)
    state: str | None = Field(None, description="State/province", max_length=50)
    zip_code: str | None = Field(None, description="ZIP/postal code", max_length=20)
    phone: str | None = Field(None, description="Phone number", max_length=20)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "phone": "(903) 693-9001",
                }
            ]
        }
    }


class VendorResponse(VendorBase):
    """Schema for vendor response."""

    id: int
    created_at: datetime
    updated_at: datetime | None = None
    full_address: str | None = Field(None, description="Formatted full address")

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "examples": [
                {
                    "id": 1,
                    "name": "Mavis Tires & Brakes",
                    "address": "603 W. Wellington ST",
                    "city": "Carthage",
                    "state": "TX",
                    "zip_code": "75633",
                    "phone": "(903) 693-9000",
                    "created_at": "2026-01-15T10:30:00",
                    "updated_at": None,
                    "full_address": "603 W. Wellington ST, Carthage, TX 75633",
                }
            ]
        },
    }


class VendorListResponse(BaseModel):
    """Schema for vendor list response."""

    vendors: list[VendorResponse]
    total: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vendors": [
                        {
                            "id": 1,
                            "name": "Mavis Tires & Brakes",
                            "city": "Carthage",
                            "state": "TX",
                            "created_at": "2026-01-15T10:30:00",
                        }
                    ],
                    "total": 1,
                }
            ]
        }
    }

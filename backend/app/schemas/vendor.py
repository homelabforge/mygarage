"""Pydantic schemas for Vendor operations."""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class VendorBase(BaseModel):
    """Base vendor schema with common fields."""

    name: str = Field(..., description="Vendor/shop name", min_length=1, max_length=100)
    address: Optional[str] = Field(None, description="Street address", max_length=500)
    city: Optional[str] = Field(None, description="City", max_length=100)
    state: Optional[str] = Field(None, description="State/province", max_length=50)
    zip_code: Optional[str] = Field(None, description="ZIP/postal code", max_length=20)
    phone: Optional[str] = Field(None, description="Phone number", max_length=20)


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

    name: Optional[str] = Field(
        None, description="Vendor/shop name", min_length=1, max_length=100
    )
    address: Optional[str] = Field(None, description="Street address", max_length=500)
    city: Optional[str] = Field(None, description="City", max_length=100)
    state: Optional[str] = Field(None, description="State/province", max_length=50)
    zip_code: Optional[str] = Field(None, description="ZIP/postal code", max_length=20)
    phone: Optional[str] = Field(None, description="Phone number", max_length=20)

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
    updated_at: Optional[datetime] = None
    full_address: Optional[str] = Field(None, description="Formatted full address")

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


class VendorPriceHistoryEntry(BaseModel):
    """Schema for a single price history entry."""

    date: str
    cost: float
    service_name: str
    service_line_item_id: int

    model_config = {"from_attributes": True}


class VendorPriceHistoryResponse(BaseModel):
    """Schema for vendor price history response."""

    vendor_id: int
    vendor_name: str
    history: list[VendorPriceHistoryEntry]
    average_cost: Optional[float] = None
    min_cost: Optional[float] = None
    max_cost: Optional[float] = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vendor_id": 1,
                    "vendor_name": "Mavis Tires & Brakes",
                    "history": [
                        {
                            "date": "2025-09-20",
                            "cost": 108.50,
                            "service_name": "Engine Oil & Filter Change",
                            "service_line_item_id": 42,
                        }
                    ],
                    "average_cost": 108.50,
                    "min_cost": 108.50,
                    "max_cost": 108.50,
                }
            ]
        }
    }

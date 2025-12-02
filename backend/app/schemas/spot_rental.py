"""Spot rental schemas for validation."""

from pydantic import BaseModel, Field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional


class SpotRentalBase(BaseModel):
    """Base spot rental schema."""

    location_name: Optional[str] = Field(None, max_length=100)
    location_address: Optional[str] = None
    check_in_date: date
    check_out_date: Optional[date] = None
    nightly_rate: Optional[Decimal] = Field(None, ge=0, le=9999.99, decimal_places=2)
    weekly_rate: Optional[Decimal] = Field(None, ge=0, le=99999.99, decimal_places=2)
    monthly_rate: Optional[Decimal] = Field(None, ge=0, le=99999.99, decimal_places=2)
    electric: Optional[Decimal] = Field(None, ge=0, le=9999.99, decimal_places=2)
    water: Optional[Decimal] = Field(None, ge=0, le=9999.99, decimal_places=2)
    waste: Optional[Decimal] = Field(None, ge=0, le=9999.99, decimal_places=2)
    total_cost: Optional[Decimal] = Field(None, ge=0, le=99999.99, decimal_places=2)
    amenities: Optional[str] = None
    notes: Optional[str] = None


class SpotRentalCreate(SpotRentalBase):
    """Schema for creating a spot rental."""

    pass


class SpotRentalUpdate(BaseModel):
    """Schema for updating a spot rental."""

    location_name: Optional[str] = Field(None, max_length=100)
    location_address: Optional[str] = None
    check_in_date: Optional[date] = None
    check_out_date: Optional[date] = None
    nightly_rate: Optional[Decimal] = Field(None, ge=0, le=9999.99, decimal_places=2)
    weekly_rate: Optional[Decimal] = Field(None, ge=0, le=99999.99, decimal_places=2)
    monthly_rate: Optional[Decimal] = Field(None, ge=0, le=99999.99, decimal_places=2)
    electric: Optional[Decimal] = Field(None, ge=0, le=9999.99, decimal_places=2)
    water: Optional[Decimal] = Field(None, ge=0, le=9999.99, decimal_places=2)
    waste: Optional[Decimal] = Field(None, ge=0, le=9999.99, decimal_places=2)
    total_cost: Optional[Decimal] = Field(None, ge=0, le=99999.99, decimal_places=2)
    amenities: Optional[str] = None
    notes: Optional[str] = None


class SpotRentalResponse(SpotRentalBase):
    """Schema for spot rental response."""

    id: int
    vin: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SpotRentalListResponse(BaseModel):
    """Schema for list of spot rentals."""

    spot_rentals: list[SpotRentalResponse]
    total: int

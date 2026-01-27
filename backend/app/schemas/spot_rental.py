"""Spot rental schemas for validation."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.spot_rental_billing import SpotRentalBillingResponse


class SpotRentalBase(BaseModel):
    """Base spot rental schema."""

    location_name: str | None = Field(None, max_length=100)
    location_address: str | None = None
    check_in_date: date
    check_out_date: date | None = None
    nightly_rate: Decimal | None = Field(None, ge=0, le=9999.99, decimal_places=2)
    weekly_rate: Decimal | None = Field(None, ge=0, le=99999.99, decimal_places=2)
    monthly_rate: Decimal | None = Field(None, ge=0, le=99999.99, decimal_places=2)
    electric: Decimal | None = Field(None, ge=0, le=9999.99, decimal_places=2)
    water: Decimal | None = Field(None, ge=0, le=9999.99, decimal_places=2)
    waste: Decimal | None = Field(None, ge=0, le=9999.99, decimal_places=2)
    total_cost: Decimal | None = Field(None, ge=0, le=99999.99, decimal_places=2)
    amenities: str | None = None
    notes: str | None = None


class SpotRentalCreate(SpotRentalBase):
    """Schema for creating a spot rental."""

    pass


class SpotRentalUpdate(BaseModel):
    """Schema for updating a spot rental."""

    location_name: str | None = Field(None, max_length=100)
    location_address: str | None = None
    check_in_date: date | None = None
    check_out_date: date | None = None
    nightly_rate: Decimal | None = Field(None, ge=0, le=9999.99, decimal_places=2)
    weekly_rate: Decimal | None = Field(None, ge=0, le=99999.99, decimal_places=2)
    monthly_rate: Decimal | None = Field(None, ge=0, le=99999.99, decimal_places=2)
    electric: Decimal | None = Field(None, ge=0, le=9999.99, decimal_places=2)
    water: Decimal | None = Field(None, ge=0, le=9999.99, decimal_places=2)
    waste: Decimal | None = Field(None, ge=0, le=9999.99, decimal_places=2)
    total_cost: Decimal | None = Field(None, ge=0, le=99999.99, decimal_places=2)
    amenities: str | None = None
    notes: str | None = None


class SpotRentalResponse(SpotRentalBase):
    """Schema for spot rental response."""

    id: int
    vin: str
    created_at: datetime
    billings: list[SpotRentalBillingResponse] = []

    model_config = {"from_attributes": True}


class SpotRentalListResponse(BaseModel):
    """Schema for list of spot rentals."""

    spot_rentals: list[SpotRentalResponse]
    total: int

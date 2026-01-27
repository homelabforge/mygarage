"""Spot rental billing schemas for request/response validation."""

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class SpotRentalBillingBase(BaseModel):
    """Base schema for billing entry."""

    billing_date: date_type = Field(..., description="Date of this billing entry")
    monthly_rate: Decimal | None = Field(None, ge=0, description="Monthly rate for this period")
    electric: Decimal | None = Field(None, ge=0, description="Electric charge")
    water: Decimal | None = Field(None, ge=0, description="Water charge")
    waste: Decimal | None = Field(None, ge=0, description="Waste charge")
    total: Decimal | None = Field(None, description="Total for this billing entry")
    notes: str | None = Field(None, max_length=1000, description="Billing notes")


class SpotRentalBillingCreate(SpotRentalBillingBase):
    """Schema for creating a billing entry."""

    pass


class SpotRentalBillingUpdate(BaseModel):
    """Schema for updating a billing entry (all fields optional)."""

    billing_date: date_type | None = None
    monthly_rate: Decimal | None = Field(None, ge=0)
    electric: Decimal | None = Field(None, ge=0)
    water: Decimal | None = Field(None, ge=0)
    waste: Decimal | None = Field(None, ge=0)
    total: Decimal | None = None
    notes: str | None = Field(None, max_length=1000)

    class Config:
        extra = "forbid"


class SpotRentalBillingResponse(SpotRentalBillingBase):
    """Schema for billing entry response."""

    id: int
    spot_rental_id: int
    created_at: datetime

    class Config:
        from_attributes = True


class SpotRentalBillingListResponse(BaseModel):
    """Schema for list of billing entries."""

    billings: list[SpotRentalBillingResponse]
    total: int

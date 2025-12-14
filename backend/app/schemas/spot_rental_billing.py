"""Spot rental billing schemas for request/response validation."""

from pydantic import BaseModel, Field
from datetime import date as date_type, datetime
from decimal import Decimal
from typing import Optional


class SpotRentalBillingBase(BaseModel):
    """Base schema for billing entry."""
    billing_date: date_type = Field(..., description="Date of this billing entry")
    monthly_rate: Optional[Decimal] = Field(None, ge=0, description="Monthly rate for this period")
    electric: Optional[Decimal] = Field(None, ge=0, description="Electric charge")
    water: Optional[Decimal] = Field(None, ge=0, description="Water charge")
    waste: Optional[Decimal] = Field(None, ge=0, description="Waste charge")
    total: Optional[Decimal] = Field(None, description="Total for this billing entry")
    notes: Optional[str] = Field(None, max_length=1000, description="Billing notes")


class SpotRentalBillingCreate(SpotRentalBillingBase):
    """Schema for creating a billing entry."""
    pass


class SpotRentalBillingUpdate(BaseModel):
    """Schema for updating a billing entry (all fields optional)."""
    billing_date: Optional[date_type] = None
    monthly_rate: Optional[Decimal] = Field(None, ge=0)
    electric: Optional[Decimal] = Field(None, ge=0)
    water: Optional[Decimal] = Field(None, ge=0)
    waste: Optional[Decimal] = Field(None, ge=0)
    total: Optional[Decimal] = None
    notes: Optional[str] = Field(None, max_length=1000)

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

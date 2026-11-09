"""Spot rental billing schemas for request/response validation."""

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas._money import OptionalMoney
from app.schemas._nullability import reject_null


class SpotRentalBillingBase(BaseModel):
    """Base schema for billing entry."""

    billing_date: date_type = Field(..., description="Date of this billing entry")
    monthly_rate: OptionalMoney = Field(None, description="Monthly rate for this period")
    electric: OptionalMoney = Field(None, description="Electric charge")
    water: OptionalMoney = Field(None, description="Water charge")
    waste: OptionalMoney = Field(None, description="Waste charge")
    total: OptionalMoney = Field(None, description="Total for this billing entry")
    notes: str | None = Field(None, max_length=1000, description="Billing notes")


class SpotRentalBillingCreate(SpotRentalBillingBase):
    """Schema for creating a billing entry."""

    pass


class SpotRentalBillingUpdate(BaseModel):
    """Schema for updating a billing entry (all fields optional)."""

    billing_date: date_type | None = None
    monthly_rate: OptionalMoney = None
    electric: OptionalMoney = None
    water: OptionalMoney = None
    waste: OptionalMoney = None
    total: OptionalMoney = None
    notes: str | None = Field(None, max_length=1000)

    # NOT NULL column: a null billing_date reached the database as a 500.
    _no_null = reject_null("billing_date")

    model_config = ConfigDict(extra="forbid")


class SpotRentalBillingResponse(SpotRentalBillingBase):
    """Schema for billing entry response."""

    # Money without the input bounds, so a stored amount past today's rules
    # still reads instead of 500ing (test_response_contract).
    monthly_rate: Decimal | None = Field(None, description="Monthly rate for this period")
    electric: Decimal | None = Field(None, description="Electric charge")
    water: Decimal | None = Field(None, description="Water charge")
    waste: Decimal | None = Field(None, description="Waste charge")
    total: Decimal | None = Field(None, description="Total for this billing entry")
    # Text without the input rules, so a stored string past today's limits
    # still reads instead of 500ing (test_response_contract).
    notes: str | None = Field(None, description="Billing notes")
    id: int
    spot_rental_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SpotRentalBillingListResponse(BaseModel):
    """Schema for list of billing entries."""

    billings: list[SpotRentalBillingResponse]
    total: int

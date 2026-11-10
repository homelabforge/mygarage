"""Spot rental schemas for validation."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas._money import OptionalMoney
from app.schemas._nullability import reject_null
from app.schemas.spot_rental_billing import SpotRentalBillingResponse


class SpotRentalBase(BaseModel):
    """Base spot rental schema."""

    location_name: str | None = Field(default=None, max_length=100)
    location_address: str | None = None
    check_in_date: date
    check_out_date: date | None = None
    nightly_rate: OptionalMoney = Field(default=None, decimal_places=2)
    weekly_rate: OptionalMoney = Field(default=None, decimal_places=2)
    monthly_rate: OptionalMoney = Field(default=None, decimal_places=2)
    electric: OptionalMoney = Field(default=None, decimal_places=2)
    water: OptionalMoney = Field(default=None, decimal_places=2)
    waste: OptionalMoney = Field(default=None, decimal_places=2)
    total_cost: OptionalMoney = Field(default=None, decimal_places=2)
    amenities: str | None = None
    notes: str | None = None


class SpotRentalCreate(SpotRentalBase):
    """Schema for creating a spot rental."""

    pass


class SpotRentalUpdate(BaseModel):
    """Schema for updating a spot rental."""

    location_name: str | None = Field(default=None, max_length=100)
    location_address: str | None = None
    check_in_date: date | None = None
    check_out_date: date | None = None
    nightly_rate: OptionalMoney = Field(default=None, decimal_places=2)
    weekly_rate: OptionalMoney = Field(default=None, decimal_places=2)
    monthly_rate: OptionalMoney = Field(default=None, decimal_places=2)
    electric: OptionalMoney = Field(default=None, decimal_places=2)
    water: OptionalMoney = Field(default=None, decimal_places=2)
    waste: OptionalMoney = Field(default=None, decimal_places=2)
    total_cost: OptionalMoney = Field(default=None, decimal_places=2)
    amenities: str | None = None
    notes: str | None = None

    # NOT NULL column: omitted keeps the stored date, null is a 422.
    _no_null = reject_null("check_in_date")


class SpotRentalResponse(SpotRentalBase):
    """Schema for spot rental response."""

    # Money without the input bounds, so a stored amount past today's rules
    # still reads instead of 500ing (test_response_contract).
    nightly_rate: Decimal | None = None
    weekly_rate: Decimal | None = None
    monthly_rate: Decimal | None = None
    electric: Decimal | None = None
    water: Decimal | None = None
    waste: Decimal | None = None
    total_cost: Decimal | None = None
    # Text without the input rules, so a stored string past today's limits
    # still reads instead of 500ing (test_response_contract).
    location_name: str | None = None
    id: int
    vin: str
    created_at: datetime
    billings: list[SpotRentalBillingResponse] = []

    model_config = {"from_attributes": True}


class SpotRentalListResponse(BaseModel):
    """Schema for list of spot rentals."""

    spot_rentals: list[SpotRentalResponse]
    total: int

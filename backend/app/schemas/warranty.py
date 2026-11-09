"""Warranty record schemas (metric canonical since v2.26.2)."""

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas._nullability import reject_null


class WarrantyLinkedItem(BaseModel):
    """A line item done under the warranty."""

    visit_id: int
    line_item_id: int
    date: date_type = Field(..., description="The visit's date")
    description: str = Field(..., description="Service description")
    cost: Decimal | None = Field(None, description="Cost for this line item")


class WarrantyRecordBase(BaseModel):
    """Base warranty record schema."""

    warranty_type: str = Field(..., description="Type of warranty coverage")
    provider: str | None = Field(None, description="Warranty provider name")
    start_date: date_type = Field(..., description="Warranty start date")
    end_date: date_type | None = Field(None, description="Warranty end date")
    mileage_limit_km: Decimal | None = Field(
        None, description="Mileage limit in kilometers if applicable", ge=0, le=99999999.99
    )
    coverage_details: str | None = Field(None, description="Details of what is covered")
    policy_number: str | None = Field(None, description="Warranty policy number")
    notes: str | None = Field(None, description="Additional notes")


class WarrantyRecordCreate(WarrantyRecordBase):
    """Schema for creating a warranty record."""

    pass


class WarrantyRecordUpdate(BaseModel):
    """Schema for updating a warranty record."""

    warranty_type: str | None = None
    provider: str | None = None
    start_date: date_type | None = None
    end_date: date_type | None = None
    mileage_limit_km: Decimal | None = Field(None, ge=0, le=99999999.99)
    coverage_details: str | None = None
    policy_number: str | None = None
    notes: str | None = None

    # NOT NULL columns: omitted keeps the stored value, null is a 422.
    _no_null = reject_null("warranty_type", "start_date")


class WarrantyRecord(WarrantyRecordBase):
    """Schema for warranty record response."""

    # No input bounds, so a stored limit past today's rules still reads
    # instead of 500ing (test_response_contract).
    mileage_limit_km: Decimal | None = Field(
        None, description="Mileage limit in kilometers if applicable"
    )
    id: int
    vin: str
    created_at: datetime
    # Not an ORM attribute, so from_attributes leaves it empty; whoever loads
    # the links sets it.
    linked_items: list[WarrantyLinkedItem] = Field(
        default_factory=list, description="Line items done under this warranty, by visit date"
    )

    model_config = ConfigDict(from_attributes=True)

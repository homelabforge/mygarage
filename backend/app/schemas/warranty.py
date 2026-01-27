"""Warranty record schemas."""

from datetime import date as date_type
from datetime import datetime

from pydantic import BaseModel, Field


class WarrantyRecordBase(BaseModel):
    """Base warranty record schema."""

    warranty_type: str = Field(..., description="Type of warranty coverage")
    provider: str | None = Field(None, description="Warranty provider name")
    start_date: date_type = Field(..., description="Warranty start date")
    end_date: date_type | None = Field(None, description="Warranty end date")
    mileage_limit: int | None = Field(
        None, description="Mileage limit if applicable", ge=0
    )
    coverage_details: str | None = Field(
        None, description="Details of what is covered"
    )
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
    mileage_limit: int | None = Field(None, ge=0)
    coverage_details: str | None = None
    policy_number: str | None = None
    notes: str | None = None


class WarrantyRecord(WarrantyRecordBase):
    """Schema for warranty record response."""

    id: int
    vin: str
    created_at: datetime

    class Config:
        from_attributes = True

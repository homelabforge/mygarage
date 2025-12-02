"""Warranty record schemas."""

from pydantic import BaseModel, Field
from datetime import date as date_type, datetime
from typing import Optional


class WarrantyRecordBase(BaseModel):
    """Base warranty record schema."""

    warranty_type: str = Field(..., description="Type of warranty coverage")
    provider: Optional[str] = Field(None, description="Warranty provider name")
    start_date: date_type = Field(..., description="Warranty start date")
    end_date: Optional[date_type] = Field(None, description="Warranty end date")
    mileage_limit: Optional[int] = Field(None, description="Mileage limit if applicable", ge=0)
    coverage_details: Optional[str] = Field(None, description="Details of what is covered")
    policy_number: Optional[str] = Field(None, description="Warranty policy number")
    notes: Optional[str] = Field(None, description="Additional notes")


class WarrantyRecordCreate(WarrantyRecordBase):
    """Schema for creating a warranty record."""

    pass


class WarrantyRecordUpdate(BaseModel):
    """Schema for updating a warranty record."""

    warranty_type: Optional[str] = None
    provider: Optional[str] = None
    start_date: Optional[date_type] = None
    end_date: Optional[date_type] = None
    mileage_limit: Optional[int] = Field(None, ge=0)
    coverage_details: Optional[str] = None
    policy_number: Optional[str] = None
    notes: Optional[str] = None


class WarrantyRecord(WarrantyRecordBase):
    """Schema for warranty record response."""

    id: int
    vin: str
    created_at: datetime

    class Config:
        from_attributes = True

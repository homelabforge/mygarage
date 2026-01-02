"""Pydantic schemas for Technical Service Bulletins (TSBs)."""

from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional


class TSBBase(BaseModel):
    """Base TSB schema with common fields."""

    tsb_number: Optional[str] = Field(None, max_length=50)
    component: str = Field(..., max_length=200)
    summary: str
    status: str = Field(
        default="pending",
        pattern="^(pending|acknowledged|applied|not_applicable|ignored)$",
    )
    source: str = Field(default="manual", pattern="^(manual|nhtsa)$")


class TSBCreate(TSBBase):
    """Schema for creating a new TSB."""

    vin: str = Field(..., min_length=17, max_length=17)
    related_service_id: Optional[int] = None


class TSBUpdate(BaseModel):
    """Schema for updating an existing TSB."""

    tsb_number: Optional[str] = Field(None, max_length=50)
    component: Optional[str] = Field(None, max_length=200)
    summary: Optional[str] = None
    status: Optional[str] = Field(
        None, pattern="^(pending|acknowledged|applied|not_applicable|ignored)$"
    )
    applied_at: Optional[datetime] = None
    related_service_id: Optional[int] = None


class TSBResponse(TSBBase):
    """Schema for TSB responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    vin: str
    applied_at: Optional[datetime] = None
    related_service_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class TSBListResponse(BaseModel):
    """Schema for list of TSBs."""

    tsbs: list[TSBResponse]
    total: int


class NHTSATSBSearchResponse(BaseModel):
    """Schema for NHTSA TSB search results."""

    found: bool
    count: int = 0
    tsbs: list[dict] = []
    error: Optional[str] = None

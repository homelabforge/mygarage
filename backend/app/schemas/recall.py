"""Recall Pydantic schemas for validation and serialization."""

import datetime as dt
from typing import Optional
from pydantic import BaseModel, Field


class RecallBase(BaseModel):
    """Base recall schema with common fields."""

    nhtsa_campaign_number: Optional[str] = Field(
        None, description="NHTSA campaign number", max_length=50
    )
    component: str = Field(
        ..., description="Component affected by recall", min_length=1, max_length=200
    )
    summary: str = Field(..., description="Summary of the recall issue", min_length=1)
    consequence: Optional[str] = Field(None, description="Potential consequences")
    remedy: Optional[str] = Field(None, description="Remedy for the recall")
    date_announced: Optional[dt.date] = Field(
        None, description="Date recall was announced"
    )
    notes: Optional[str] = Field(None, description="User notes about the recall")


class RecallCreate(RecallBase):
    """Schema for creating a new recall."""

    vin: str = Field(..., description="Vehicle VIN", min_length=17, max_length=17)
    is_resolved: bool = Field(
        default=False, description="Whether recall has been resolved"
    )


class RecallUpdate(BaseModel):
    """Schema for updating an existing recall."""

    nhtsa_campaign_number: Optional[str] = Field(
        None, description="NHTSA campaign number", max_length=50
    )
    component: Optional[str] = Field(
        None, description="Component affected by recall", min_length=1, max_length=200
    )
    summary: Optional[str] = Field(
        None, description="Summary of the recall issue", min_length=1
    )
    consequence: Optional[str] = Field(None, description="Potential consequences")
    remedy: Optional[str] = Field(None, description="Remedy for the recall")
    date_announced: Optional[dt.date] = Field(
        None, description="Date recall was announced"
    )
    notes: Optional[str] = Field(None, description="User notes about the recall")
    is_resolved: Optional[bool] = Field(
        None, description="Whether recall has been resolved"
    )


class RecallResponse(RecallBase):
    """Schema for recall response."""

    id: int
    vin: str
    is_resolved: bool
    resolved_at: Optional[dt.datetime] = None
    created_at: dt.datetime

    class Config:
        from_attributes = True


class RecallListResponse(BaseModel):
    """Schema for list of recalls."""

    recalls: list[RecallResponse]
    total: int
    active_count: int
    resolved_count: int

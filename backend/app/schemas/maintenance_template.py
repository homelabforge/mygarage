"""Pydantic schemas for Maintenance Templates."""

import datetime as dt
from typing import Optional
from pydantic import BaseModel, Field


class MaintenanceTemplateBase(BaseModel):
    """Base maintenance template schema with common fields."""

    template_source: str = Field(..., max_length=200)
    template_version: Optional[str] = Field(None, max_length=50)
    template_data: dict = Field(...)
    reminders_created: int = Field(default=0)


class MaintenanceTemplateCreate(MaintenanceTemplateBase):
    """Schema for creating a new maintenance template record."""

    vin: str = Field(..., min_length=17, max_length=17)
    created_by: str = Field(default="auto", max_length=20)


class MaintenanceTemplateUpdate(BaseModel):
    """Schema for updating an existing maintenance template record."""

    template_version: Optional[str] = Field(None, max_length=50)
    reminders_created: Optional[int] = None


class MaintenanceTemplateResponse(MaintenanceTemplateBase):
    """Schema for maintenance template response."""

    id: int
    vin: str
    applied_at: dt.datetime
    created_by: str
    created_at: dt.datetime
    updated_at: Optional[dt.datetime] = None

    class Config:
        from_attributes = True


class MaintenanceTemplateListResponse(BaseModel):
    """Schema for list of maintenance templates."""

    templates: list[MaintenanceTemplateResponse]
    total: int


class TemplateSearchResponse(BaseModel):
    """Schema for template search results from GitHub."""

    found: bool
    template_url: Optional[str] = None
    template_path: Optional[str] = None
    template_data: Optional[dict] = None
    error: Optional[str] = None


class TemplateApplyRequest(BaseModel):
    """Schema for applying a template to a vehicle."""

    vin: str = Field(..., min_length=17, max_length=17)
    duty_type: str = Field(default="normal")  # "normal" or "severe"
    current_mileage: Optional[int] = Field(None, ge=0)


class TemplateApplyResponse(BaseModel):
    """Schema for template application response."""

    success: bool
    reminders_created: int
    template_source: str
    template_version: Optional[str] = None
    error: Optional[str] = None

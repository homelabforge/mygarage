"""Settings Pydantic schemas for validation and serialization."""

import datetime as dt
from typing import Optional
from pydantic import BaseModel, Field


class SettingBase(BaseModel):
    """Base setting schema."""

    value: Optional[str] = Field(None, description="Setting value")
    category: str = Field("general", description="Setting category")
    description: Optional[str] = Field(None, description="Setting description")
    encrypted: bool = Field(False, description="Whether the value is encrypted")


class SettingCreate(SettingBase):
    """Schema for creating a setting."""

    key: str = Field(..., description="Setting key", min_length=1, max_length=50)


class SettingUpdate(BaseModel):
    """Schema for updating a setting."""

    value: Optional[str] = Field(None, description="Setting value")
    category: Optional[str] = Field(None, description="Setting category")
    description: Optional[str] = Field(None, description="Setting description")
    encrypted: Optional[bool] = Field(
        None, description="Whether the value is encrypted"
    )


class SettingResponse(SettingBase):
    """Schema for setting response."""

    key: str
    created_at: dt.datetime
    updated_at: dt.datetime

    class Config:
        from_attributes = True


class SettingsListResponse(BaseModel):
    """Schema for list of settings."""

    settings: list[SettingResponse]
    total: int


class SettingsBatchUpdate(BaseModel):
    """Schema for batch updating settings."""

    settings: dict[str, str] = Field(
        ..., description="Dictionary of key-value pairs to update"
    )


class SystemInfoResponse(BaseModel):
    """Schema for system information."""

    app_name: str
    app_version: str
    python_version: str
    database_url: str
    data_directory: str
    total_vehicles: int
    database_size_mb: float
    uptime_seconds: float

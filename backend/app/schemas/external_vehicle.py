"""Schemas for lightweight external vehicles (family/friend reference)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.utils.vin import validate_vin


def _normalize_optional_vin(v: Any) -> str | None:
    """Empty/whitespace → None; otherwise uppercase + validate format."""
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError("VIN must be a string")
    cleaned = v.strip().upper()
    if not cleaned:
        return None
    is_valid, error = validate_vin(cleaned)
    if not is_valid:
        raise ValueError(error or "Invalid VIN format")
    return cleaned


class ExternalVehicleCreate(BaseModel):
    nickname: str = Field(..., min_length=1, max_length=100)
    vin: str | None = Field(None, min_length=17, max_length=17)
    year: int | None = Field(None, ge=1900, le=2100)
    make: str | None = Field(None, max_length=50)
    model: str | None = Field(None, max_length=50)
    vehicle_type: str | None = Field(None, max_length=30)
    contact_name: str | None = Field(None, max_length=100)
    contact_phone: str | None = Field(None, max_length=40)
    notes: str | None = None

    @field_validator("vin", mode="before")
    @classmethod
    def validate_vin_format(cls, v: Any) -> str | None:
        return _normalize_optional_vin(v)


class ExternalVehicleUpdate(BaseModel):
    nickname: str | None = Field(None, min_length=1, max_length=100)
    vin: str | None = Field(None, min_length=17, max_length=17)
    year: int | None = Field(None, ge=1900, le=2100)
    make: str | None = Field(None, max_length=50)
    model: str | None = Field(None, max_length=50)
    vehicle_type: str | None = Field(None, max_length=30)
    contact_name: str | None = Field(None, max_length=100)
    contact_phone: str | None = Field(None, max_length=40)
    notes: str | None = None

    @field_validator("vin", mode="before")
    @classmethod
    def validate_vin_format(cls, v: Any) -> str | None:
        return _normalize_optional_vin(v)


class ExternalVehicleResponse(BaseModel):
    id: int
    nickname: str
    vin: str | None = None
    year: int | None = None
    make: str | None = None
    model: str | None = None
    vehicle_type: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class ExternalVehicleListResponse(BaseModel):
    vehicles: list[ExternalVehicleResponse]
    total: int

"""Schemas for lightweight external vehicles (customer / reference)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ExternalVehicleKind = Literal["customer", "reference"]


class ExternalVehicleCreate(BaseModel):
    kind: ExternalVehicleKind
    nickname: str = Field(..., min_length=1, max_length=100)
    year: int | None = Field(None, ge=1900, le=2100)
    make: str | None = Field(None, max_length=50)
    model: str | None = Field(None, max_length=50)
    vehicle_type: str | None = Field(None, max_length=30)
    contact_name: str | None = Field(None, max_length=100)
    contact_phone: str | None = Field(None, max_length=40)
    notes: str | None = None
    last_service_note: str | None = Field(None, max_length=200)


class ExternalVehicleUpdate(BaseModel):
    kind: ExternalVehicleKind | None = None
    nickname: str | None = Field(None, min_length=1, max_length=100)
    year: int | None = Field(None, ge=1900, le=2100)
    make: str | None = Field(None, max_length=50)
    model: str | None = Field(None, max_length=50)
    vehicle_type: str | None = Field(None, max_length=30)
    contact_name: str | None = Field(None, max_length=100)
    contact_phone: str | None = Field(None, max_length=40)
    notes: str | None = None
    last_service_note: str | None = Field(None, max_length=200)


class ExternalVehicleResponse(BaseModel):
    id: int
    kind: ExternalVehicleKind
    nickname: str
    year: int | None = None
    make: str | None = None
    model: str | None = None
    vehicle_type: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    notes: str | None = None
    last_service_note: str | None = None
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class ExternalVehicleListResponse(BaseModel):
    vehicles: list[ExternalVehicleResponse]
    total: int

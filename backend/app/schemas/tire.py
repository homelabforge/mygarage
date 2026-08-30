"""Pydantic schemas for tire position / tread tracking."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

TirePosition = Literal["FL", "FR", "RL", "RR", "SPARE"]
TIRE_POSITIONS: tuple[str, ...] = ("FL", "FR", "RL", "RR", "SPARE")


class TireBase(BaseModel):
    """Shared tire fields."""

    position: TirePosition
    brand: str | None = Field(None, max_length=80)
    model_name: str | None = Field(None, max_length=80)
    size: str | None = Field(None, max_length=40)
    dot_code: str | None = Field(None, max_length=20)
    installed_date: date_type | None = None
    tread_depth_mm: Decimal | None = Field(None, ge=0, le=30)
    pressure_kpa: Decimal | None = Field(None, ge=0, le=1000)
    min_tread_mm: Decimal | None = Field(
        Decimal("2.0"),
        ge=0,
        le=10,
        description="Wear-out threshold in mm; drives reminder hooks",
    )
    notes: str | None = None


class TireCreate(TireBase):
    """Create / upsert a tire at a position."""

    vin: str = Field(..., max_length=17)


class TireUpdate(BaseModel):
    """Partial tire update."""

    brand: str | None = Field(None, max_length=80)
    model_name: str | None = Field(None, max_length=80)
    size: str | None = Field(None, max_length=40)
    dot_code: str | None = Field(None, max_length=20)
    installed_date: date_type | None = None
    tread_depth_mm: Decimal | None = Field(None, ge=0, le=30)
    pressure_kpa: Decimal | None = Field(None, ge=0, le=1000)
    min_tread_mm: Decimal | None = Field(None, ge=0, le=10)
    notes: str | None = None


class TireReadingCreate(BaseModel):
    """Record a tread/pressure reading (updates the parent tire's latest depth).

    Tread is OPTIONAL (#152): the reporter tracks a slow pressure leak and owns
    no tread gauge, and a required tread beside an optional odometer meant they
    could not record a pressure at all. What is required is that a reading carry
    at least one measurement (see ``_at_least_one_measurement``).
    """

    recorded_at: date_type
    odometer_km: Decimal | None = Field(None, ge=0)
    tread_depth_mm: Decimal | None = Field(None, ge=0, le=30)
    pressure_kpa: Decimal | None = Field(None, ge=0, le=1000)
    notes: str | None = None

    @model_validator(mode="after")
    def _at_least_one_measurement(self) -> TireReadingCreate:
        """Reject a reading that measures nothing.

        ``odometer_km`` deliberately does not count. It is context for the wear
        projection, not an observation of the tire, so a date-plus-odometer row
        would add a history entry that says nothing about the tire and would
        still be picked up by ``_project_wear`` as the newest reading.

        :raises ValueError: when both tread and pressure are absent.
        """
        if self.tread_depth_mm is None and self.pressure_kpa is None:
            raise ValueError("A reading needs a tread depth, a pressure, or both")
        return self


class TireReadingResponse(BaseModel):
    """Tire reading response."""

    id: int
    tire_id: int
    vin: str
    position: str
    recorded_at: date_type
    odometer_km: Decimal | None
    tread_depth_mm: Decimal | None
    pressure_kpa: Decimal | None
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TireResponse(TireBase):
    """Tire with optional wear projection."""

    id: int
    vin: str
    created_at: datetime
    updated_at: datetime | None = None
    # Estimated km remaining until min_tread_mm based on last two readings.
    projected_km_remaining: Decimal | None = None
    # Estimated calendar date of wear-out (null when projection unavailable).
    projected_wear_date: date_type | None = None
    below_threshold: bool = False
    readings: list[TireReadingResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}

    @field_validator("position")
    @classmethod
    def _position_ok(cls, v: str) -> str:
        if v not in TIRE_POSITIONS:
            raise ValueError(f"position must be one of {TIRE_POSITIONS}")
        return v


class TireListResponse(BaseModel):
    """All tires for a vehicle."""

    tires: list[TireResponse]
    total: int

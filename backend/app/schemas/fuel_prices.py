"""Fuel prices near a station (#211)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class FuelPriceResponse(BaseModel):
    """One pump price at one station."""

    grade: str = Field(..., description="EN 16942 label (E5, E10, B7, E85, LPG…)")
    octane: int | None = Field(None, description="RON where the label alone is ambiguous")
    price: Decimal = Field(..., description="Per litre (per kilogram for a gas)")
    currency: str
    updated_at: datetime | None = None


class StationPricesResponse(BaseModel):
    external_id: str
    name: str | None = None
    address: str | None = None
    city: str | None = None
    postal_code: str | None = None
    latitude: float
    longitude: float
    distance_km: float
    prices: list[FuelPriceResponse] = Field(default_factory=list)


class FuelPricesResponse(BaseModel):
    """The stations near a point, from the provider the country names.

    `provider` is null when no profile applies to the country, when the
    profile names no source, or when the source is turned off: the form then
    shows nothing rather than an error.
    """

    provider: str | None = None
    currency: str | None = None
    country: str | None = None
    stations: list[StationPricesResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

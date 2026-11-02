"""What every fuel price provider gives back, and the shape of a provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class FuelPrice:
    """One pump price at one station."""

    #: The EN 16942 label (E5, E10, B7, E85, LPG…), as ``fuel_records.fuel_grade``.
    grade: str
    #: The RON printed with the label where the label alone is ambiguous
    #: (E5 at 95 or 98); None where the grade says it all.
    octane: int | None
    #: Per litre (or per kilogram for a gas), in ``currency``.
    price: Decimal
    currency: str
    #: When the station last reported this price.
    updated_at: datetime | None = None


@dataclass(frozen=True)
class StationPrices:
    """One station and the prices it reports."""

    #: The provider's own identifier for the station.
    external_id: str
    name: str | None
    address: str | None
    city: str | None
    postal_code: str | None
    latitude: float
    longitude: float
    #: From the point asked about, in kilometres.
    distance_km: float
    prices: list[FuelPrice] = field(default_factory=list)


class FuelPriceProvider(Protocol):
    #: The id a country profile names in ``data_sources.fuel_prices``.
    id: str
    #: The ISO 4217 code of every price this provider reports.
    currency: str

    async def enabled(self, db: AsyncSession) -> bool:
        """The instance setting that turns the provider off."""
        ...

    async def nearby(
        self, db: AsyncSession, latitude: float, longitude: float, *, radius_km: float, limit: int
    ) -> list[StationPrices]:
        """The stations within ``radius_km`` of the point, nearest first. May raise."""
        ...

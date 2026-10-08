"""What every recall provider gives back, and the shape of a provider."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle
from app.schemas.country_profile import CountryProfile

#: ``recalls.source`` values. ``manual`` is a row a person typed.
SOURCE_NHTSA = "nhtsa"
SOURCE_RAPPELCONSO = "rappelconso"
SOURCE_MANUAL = "manual"
RECALL_SOURCES: tuple[str, ...] = (SOURCE_NHTSA, SOURCE_RAPPELCONSO, SOURCE_MANUAL)


@dataclass(frozen=True)
class RecallHit:
    """One recall a provider found for a vehicle, before it is stored."""

    source: str
    #: The provider's own identifier (an NHTSA campaign number, a RappelConso
    #: notice id): with ``source`` it is what keeps a recall from being stored
    #: twice.
    external_id: str
    external_url: str | None
    component: str
    summary: str
    consequence: str | None = None
    remedy: str | None = None
    date_announced: date | None = None
    #: 0 to 100: how surely the notice concerns THIS vehicle. NHTSA answers by
    #: make, model and year (100); RappelConso has no VIN, so a match on the
    #: make, the model and the production dates is scored.
    match_confidence: int = 100


class RecallProvider(Protocol):
    name: str

    def applies_to(self, vehicle: Vehicle, profile: CountryProfile | None) -> bool:
        """Whether this source covers the vehicle's country."""
        ...

    async def enabled(self, db: AsyncSession) -> bool:
        """The instance setting that turns the source off."""
        ...

    async def fetch(self, db: AsyncSession, vehicle: Vehicle) -> list[RecallHit]:
        """The recalls the source lists for the vehicle. May raise."""
        ...

"""Which recall providers a vehicle gets (#211)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vehicle import Vehicle
from app.schemas.country_profile import CountryProfile
from app.services.recalls.base import RecallProvider
from app.services.recalls.nhtsa import NHTSARecallProvider
from app.services.recalls.rappelconso import RappelConsoProvider

PROVIDERS: tuple[RecallProvider, ...] = (NHTSARecallProvider(), RappelConsoProvider())


def provider_by_name(name: str) -> RecallProvider | None:
    return next((p for p in PROVIDERS if p.name == name), None)


async def providers_for(
    db: AsyncSession, vehicle: Vehicle, profile: CountryProfile | None
) -> list[RecallProvider]:
    """The enabled providers whose country covers the vehicle, in order."""
    chosen: list[RecallProvider] = []
    for provider in PROVIDERS:
        if provider.applies_to(vehicle, profile) and await provider.enabled(db):
            chosen.append(provider)
    return chosen

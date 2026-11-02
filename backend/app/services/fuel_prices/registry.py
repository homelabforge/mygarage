"""Which fuel price provider a country gets (#211)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.country_profile import CountryProfile
from app.services.fuel_prices.base import FuelPriceProvider
from app.services.fuel_prices.france import FrenchFuelPriceProvider

PROVIDERS: tuple[FuelPriceProvider, ...] = (FrenchFuelPriceProvider(),)


def provider_by_id(provider_id: str | None) -> FuelPriceProvider | None:
    if not provider_id:
        return None
    return next((p for p in PROVIDERS if p.id == provider_id), None)


def provider_for(profile: CountryProfile | None) -> FuelPriceProvider | None:
    """The provider the profile names, or None (no profile, or none named)."""
    if profile is None:
        return None
    return provider_by_id(profile.data_sources.fuel_prices)


async def enabled_provider_for(
    db: AsyncSession, profile: CountryProfile | None
) -> FuelPriceProvider | None:
    provider = provider_for(profile)
    if provider is None or not await provider.enabled(db):
        return None
    return provider

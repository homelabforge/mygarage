"""Fuel prices near a point, or near an address-book station (#211).

The provider follows the country profile (`data_sources.fuel_prices`):
France's « flux instantané » today. Without a profile, a named source or
the source turned on, the answer has `provider: null` and no stations, so
the fill-up form shows nothing rather than an error; a source that fails
answers a warning the same way.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.countries import normalize_country_code
from app.database import get_db
from app.models import AddressBookEntry
from app.models.user import User
from app.schemas.fuel_prices import FuelPricesResponse, StationPricesResponse
from app.services.auth import require_auth
from app.services.country_profile_service import instance_default_country, profile_for_country
from app.services.fuel_prices.registry import enabled_provider_for
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

fuel_prices_router = APIRouter(prefix="/api/fuel-prices", tags=["Fuel prices"])
address_book_fuel_prices_router = APIRouter(prefix="/api/address-book", tags=["Fuel prices"])

DEFAULT_RADIUS_KM = 2.0


async def _country(db: AsyncSession, country: str | None, current_user: User | None) -> str | None:
    """The country asked for, else the caller's, else the instance's."""
    code = normalize_country_code(country)
    if code:
        return code
    if current_user is not None:
        code = normalize_country_code(current_user.country)
        if code:
            return code
    return await instance_default_country(db)


async def nearby_prices(
    db: AsyncSession,
    *,
    latitude: float,
    longitude: float,
    radius_km: float,
    limit: int,
    country: str | None,
) -> FuelPricesResponse:
    provider = await enabled_provider_for(db, profile_for_country(country))
    if provider is None:
        return FuelPricesResponse(country=country)
    try:
        stations = await provider.nearby(db, latitude, longitude, radius_km=radius_km, limit=limit)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Fuel price provider %s failed: %s", provider.id, sanitize_for_log(exc))
        return FuelPricesResponse(
            provider=provider.id,
            currency=provider.currency,
            country=country,
            warnings=[f"{provider.id}: request failed"],
        )
    return FuelPricesResponse(
        provider=provider.id,
        currency=provider.currency,
        country=country,
        stations=[StationPricesResponse.model_validate(s, from_attributes=True) for s in stations],
    )


@fuel_prices_router.get("/nearby", response_model=FuelPricesResponse)
async def fuel_prices_nearby(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(DEFAULT_RADIUS_KM, gt=0, le=25),
    limit: int = Query(5, ge=1, le=20),
    country: str | None = Query(None, min_length=2, max_length=2),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> FuelPricesResponse:
    """The stations near a point, nearest first, with their pump prices."""
    resolved = await _country(db, country, current_user)
    return await nearby_prices(
        db, latitude=lat, longitude=lon, radius_km=radius_km, limit=limit, country=resolved
    )


@address_book_fuel_prices_router.get("/{entry_id}/fuel-prices", response_model=FuelPricesResponse)
async def address_book_fuel_prices(
    entry_id: int,
    radius_km: float = Query(DEFAULT_RADIUS_KM, gt=0, le=25),
    limit: int = Query(5, ge=1, le=20),
    country: str | None = Query(None, min_length=2, max_length=2),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
) -> FuelPricesResponse:
    """The prices at (and right around) a saved station. 404 for an entry
    the garage does not have; 422 for one without coordinates."""
    entry = (
        await db.execute(select(AddressBookEntry).where(AddressBookEntry.id == entry_id))
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Address book entry not found")
    if entry.latitude is None or entry.longitude is None:
        raise HTTPException(status_code=422, detail="This station has no coordinates")
    resolved = await _country(db, country, current_user)
    return await nearby_prices(
        db,
        latitude=float(entry.latitude),
        longitude=float(entry.longitude),
        radius_km=radius_km,
        limit=limit,
        country=resolved,
    )

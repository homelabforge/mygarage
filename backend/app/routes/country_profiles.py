"""Country profiles, read-only: what the frontend needs to adapt its forms."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path

from app.models.user import User
from app.schemas.country_profile import CountryProfile, CountryProfileSummary
from app.services import country_profile_service
from app.services.auth import require_auth

router = APIRouter(prefix="/api/country-profiles", tags=["country-profiles"])


@router.get("", response_model=list[CountryProfileSummary])
async def list_country_profiles(
    _: User | None = Depends(require_auth),
) -> list[CountryProfileSummary]:
    """Every shipped profile, the ``EU`` baseline included."""
    return country_profile_service.list_profiles()


@router.get("/{country}", response_model=CountryProfile)
async def get_country_profile(
    country: str = Path(..., pattern=r"^[A-Za-z]{2}$"),
    _: User | None = Depends(require_auth),
) -> CountryProfile:
    """The profile a country code resolves to.

    A member state without a file of its own answers with the ``EU`` baseline
    (its ``country`` field says ``EU``); a code with no profile is a 404.
    """
    profile = country_profile_service.profile_for_country(country)
    if profile is None:
        raise HTTPException(status_code=404, detail="No profile for this country")
    return profile

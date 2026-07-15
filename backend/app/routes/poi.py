"""POI (Points of Interest) discovery API endpoints."""

import asyncio
import logging
import time
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.address_book import AddressBookEntry
from app.models.user import User
from app.schemas.address_book import AddressBookEntryCreate, AddressBookEntryResponse
from app.schemas.poi import (
    EVChargingMetadata,
    POIRecommendation,
    POIRecommendationsResponse,
    POIResult,
    POISearchRequest,
    POISearchResponse,
)
from app.services.auth import require_auth
from app.services.poi.base import POICategory
from app.services.poi_discovery import POIDiscoveryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/poi", tags=["POI Discovery"])

# ---------------------------------------------------------------------------
# Geocoding (Phase 3.9 / issue #69)
# ---------------------------------------------------------------------------
# rc1's POI search only worked from the device's GPS — there was no way
# to pick a fixed point on a map (e.g. "search around my Warsaw hotel").
# We proxy through Nominatim, OpenStreetMap's free geocoder.
#
# Nominatim's usage policy: <= 1 req/sec, identifying User-Agent. The
# in-process rate limiter below is single-process (good enough for a
# single-instance homelab deploy); high-traffic users should switch to
# a dedicated geocoder. The ``/api/poi/geocode`` endpoint is auth-only,
# which already throttles abuse.
# ---------------------------------------------------------------------------

_NOMINATIM_BASE = "https://nominatim.openstreetmap.org/search"
_NOMINATIM_USER_AGENT = "MyGarage/2.27 (https://github.com/homelabforge/mygarage)"
_NOMINATIM_MIN_INTERVAL_S = 1.0
_nominatim_lock = asyncio.Lock()
_nominatim_last_call = 0.0


class GeocodeResult(BaseModel):
    """A single geocoding hit."""

    display_name: str
    latitude: float
    longitude: float


class GeocodeResponse(BaseModel):
    results: list[GeocodeResult]
    source: str = "nominatim"


@router.get("/geocode", response_model=GeocodeResponse)
async def geocode_address(
    q: str = Query(..., min_length=2, max_length=200, description="Address or place name"),
    limit: int = Query(5, ge=1, le=10),
    current_user: User | None = Depends(require_auth),
):
    """Geocode a free-form address via Nominatim (OpenStreetMap).

    Surfaced by issue #69: rc1's POI search only worked from the
    device's current GPS. With this endpoint the frontend can offer
    "Search by address" as a parallel entry point.
    """
    global _nominatim_last_call

    # Polite rate limiting — Nominatim's ToS asks for max 1 req/sec.
    async with _nominatim_lock:
        wait_for = _NOMINATIM_MIN_INTERVAL_S - (time.monotonic() - _nominatim_last_call)
        if wait_for > 0:
            await asyncio.sleep(wait_for)
        _nominatim_last_call = time.monotonic()

    params = {
        "q": q,
        "format": "json",
        "limit": str(limit),
        "addressdetails": "0",
    }
    headers = {"User-Agent": _NOMINATIM_USER_AGENT}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(_NOMINATIM_BASE, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except httpx.TimeoutException as e:
        logger.warning("Nominatim timeout for %r: %s", q, e)
        raise HTTPException(status_code=504, detail="Geocoding service timed out") from e
    except httpx.HTTPError as e:
        logger.warning("Nominatim HTTP error for %r: %s", q, e)
        raise HTTPException(status_code=502, detail="Geocoding service unavailable") from e

    results = [
        GeocodeResult(
            display_name=str(item.get("display_name") or ""),
            latitude=float(item["lat"]),
            longitude=float(item["lon"]),
        )
        for item in payload
        if "lat" in item and "lon" in item
    ]
    return GeocodeResponse(results=results)


@router.post("/search", response_model=POISearchResponse)
async def search_nearby_pois(
    search_request: POISearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Search for nearby Points of Interest across multiple categories.

    Args:
        search_request: Search parameters (latitude, longitude, radius, categories)
        db: Database session
        current_user: Authenticated user

    Returns:
        POISearchResponse with results from configured provider

    Notes:
        - Tries providers in priority order (TomTom → OSM → etc.)
        - Supports multiple simultaneous category searches
        - Returns empty results on error (graceful degradation)
        - Categories: auto_shop, rv_shop, ev_charging, gas_station
    """
    service = POIDiscoveryService(db)

    try:
        # Convert category strings to POICategory enums
        categories = [POICategory(cat) for cat in search_request.categories]

        # Search using multi-provider system
        results, source = await service.search_nearby_pois(
            latitude=search_request.latitude,
            longitude=search_request.longitude,
            radius_meters=search_request.radius_meters or 8000,
            categories=categories,
        )

        # Convert results to POIResult models with proper metadata typing
        poi_results = []
        for r in results:
            # Parse metadata based on category
            metadata = None
            if r.get("metadata"):
                if r["poi_category"] == "ev_charging":
                    metadata = EVChargingMetadata(**r["metadata"])

            poi_results.append(
                POIResult(
                    business_name=r["business_name"],
                    address=r.get("address"),
                    city=r.get("city"),
                    state=r.get("state"),
                    zip_code=r.get("zip_code"),
                    phone=r.get("phone"),
                    latitude=r["latitude"],
                    longitude=r["longitude"],
                    source=r["source"],
                    external_id=r.get("external_id"),
                    rating=r.get("rating"),
                    distance_meters=r.get("distance_meters"),
                    website=r.get("website"),
                    poi_category=r["poi_category"],
                    metadata=metadata,
                )
            )

        return POISearchResponse(
            results=poi_results,
            count=len(poi_results),
            source=source,
            latitude=search_request.latitude,
            longitude=search_request.longitude,
            radius_meters=search_request.radius_meters or 8000,
        )

    except Exception as e:
        logger.error("POI search failed: %s", str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to search for POIs")


@router.post("/save", response_model=AddressBookEntryResponse, status_code=201)
async def save_discovered_poi(
    entry_data: AddressBookEntryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Save a discovered POI to the address book.

    Args:
        entry_data: Address book entry data
        db: Database session
        current_user: Authenticated user

    Returns:
        Created AddressBookEntry

    Notes:
        - Source should be set to provider name (tomtom, osm, google, etc.)
        - Category defaults to 'service'
        - poi_category should be set (one of POICategory: auto_shop,
          rv_shop, ev_charging, gas_station, propane)
        - metadata can contain category-specific JSON data
    """
    # Validate poi_category if provided
    entry_dict = entry_data.model_dump()
    poi_category = entry_dict.get("poi_category")
    if poi_category:
        try:
            POICategory(poi_category)
        except ValueError:
            valid = ", ".join(c.value for c in POICategory)
            raise HTTPException(
                status_code=400,
                detail=f"Invalid poi_category: {poi_category}. Must be one of: {valid}",
            )

    # Create address book entry
    entry = AddressBookEntry(**entry_dict)

    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    logger.info(
        "Saved discovered POI: %s (category: %s)",
        entry.business_name,
        entry.poi_category,
    )

    return AddressBookEntryResponse.model_validate(entry)


@router.get("/recommendations", response_model=POIRecommendationsResponse)
async def get_poi_recommendations(
    category: str | None = None,
    limit: int = Query(5, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Get recommended POIs based on usage history.

    Args:
        category: Optional POI category filter (auto_shop, rv_shop, ev_charging, gas_station)
        limit: Maximum number of recommendations (default: 5)
        db: Database session
        current_user: Authenticated user

    Returns:
        POIRecommendationsResponse with top POIs by usage

    Notes:
        - Returns POIs with category='service' OR poi_category is set
        - Sorted by usage_count DESC (most used first)
        - Only includes POIs that have been used at least once
        - Can filter by specific poi_category if provided
    """
    # Validate category if provided
    if category:
        try:
            POICategory(category)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid category: {category}. Must be one of: auto_shop, rv_shop, ev_charging, gas_station",
            )

    # Build query conditions
    conditions = [AddressBookEntry.usage_count > 0]

    # Filter by category if provided
    if category:
        conditions.append(AddressBookEntry.poi_category == category)
    else:
        # Show all service-related entries (backward compatibility)
        conditions.append(
            or_(
                AddressBookEntry.category == "service",
                AddressBookEntry.poi_category.isnot(None),
            )
        )

    # Get POIs from address book sorted by usage_count
    query = (
        select(AddressBookEntry)
        .where(and_(*conditions))
        .order_by(AddressBookEntry.usage_count.desc())
        .limit(limit)
    )

    result = await db.execute(query)
    pois = result.scalars().all()

    recommendations = [
        POIRecommendation(
            id=poi.id,
            business_name=poi.business_name,
            address=poi.address,
            city=poi.city,
            state=poi.state,
            phone=poi.phone,
            usage_count=poi.usage_count,
            rating=poi.rating,
            user_rating=poi.user_rating,
            poi_category=poi.poi_category,
        )
        for poi in pois
    ]

    return POIRecommendationsResponse(
        recommendations=recommendations,
        count=len(recommendations),
    )


@router.post("/increment-usage/{poi_id}", status_code=204)
async def increment_poi_usage(
    poi_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Increment usage count for a POI.

    Called when creating service record or using this POI.

    Args:
        poi_id: Address book entry ID
        db: Database session
        current_user: Authenticated user

    Returns:
        None (204 No Content)

    Raises:
        HTTPException: 404 if POI not found
    """
    result = await db.execute(select(AddressBookEntry).where(AddressBookEntry.id == poi_id))
    poi = result.scalar_one_or_none()

    if not poi:
        raise HTTPException(status_code=404, detail="POI not found")

    poi.usage_count += 1
    poi.last_used = datetime.now()

    await db.commit()

    logger.info("Incremented usage for POI %s (now %d)", poi.business_name, poi.usage_count)

    return None

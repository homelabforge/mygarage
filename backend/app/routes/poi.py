"""POI (Points of Interest) discovery API endpoints."""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from datetime import datetime

from app.database import get_db
from app.models.user import User
from app.models.address_book import AddressBookEntry
from app.schemas.poi import (
    POISearchRequest,
    POISearchResponse,
    POIResult,
    POIRecommendationsResponse,
    POIRecommendation,
    EVChargingMetadata,
    FuelStationMetadata,
)
from app.schemas.address_book import AddressBookEntryCreate, AddressBookEntryResponse
from app.services.auth import require_auth
from app.services.poi_discovery import POIDiscoveryService
from app.services.poi.base import POICategory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/poi", tags=["POI Discovery"])


@router.post("/search", response_model=POISearchResponse)
async def search_nearby_pois(
    search_request: POISearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
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
        - Categories: auto_shop, rv_shop, ev_charging, fuel_station
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
                elif r["poi_category"] == "fuel_station":
                    metadata = FuelStationMetadata(**r["metadata"])

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
        raise HTTPException(
            status_code=500, detail=f"Failed to search for POIs: {str(e)}"
        )


@router.post("/save", response_model=AddressBookEntryResponse, status_code=201)
async def save_discovered_poi(
    entry_data: AddressBookEntryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
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
        - poi_category should be set (auto_shop, rv_shop, ev_charging, fuel_station)
        - metadata can contain category-specific JSON data
    """
    # Validate poi_category if provided
    entry_dict = entry_data.model_dump()
    poi_category = entry_dict.get("poi_category")
    if poi_category:
        try:
            POICategory(poi_category)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid poi_category: {poi_category}. Must be one of: auto_shop, rv_shop, ev_charging, fuel_station",
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
    category: Optional[str] = None,
    limit: int = 5,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(require_auth),
):
    """Get recommended POIs based on usage history.

    Args:
        category: Optional POI category filter (auto_shop, rv_shop, ev_charging, fuel_station)
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
                detail=f"Invalid category: {category}. Must be one of: auto_shop, rv_shop, ev_charging, fuel_station",
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
    current_user: Optional[User] = Depends(require_auth),
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
    result = await db.execute(
        select(AddressBookEntry).where(AddressBookEntry.id == poi_id)
    )
    poi = result.scalar_one_or_none()

    if not poi:
        raise HTTPException(status_code=404, detail="POI not found")

    poi.usage_count += 1
    poi.last_used = datetime.now()

    await db.commit()

    logger.info(
        "Incremented usage for POI %s (now %d)", poi.business_name, poi.usage_count
    )

    return None

"""Shop discovery API endpoints."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.address_book import AddressBookEntry
from app.models.user import User
from app.schemas.address_book import AddressBookEntryCreate, AddressBookEntryResponse
from app.schemas.shop_discovery import (
    PlaceResult,
    ShopRecommendation,
    ShopRecommendationsResponse,
    ShopSearchRequest,
    ShopSearchResponse,
)
from app.services.auth import require_auth
from app.services.shop_discovery import ShopDiscoveryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/shop-discovery", tags=["Shop Discovery"])


@router.post("/search", response_model=ShopSearchResponse)
async def search_nearby_shops(
    search_request: ShopSearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Search for nearby auto repair shops using TomTom or OSM.

    Args:
        search_request: Search parameters (latitude, longitude, radius)
        db: Database session
        current_user: Authenticated user

    Returns:
        ShopSearchResponse with results from TomTom or OSM

    Notes:
        - Tries TomTom API first (if configured)
        - Falls back to OpenStreetMap if TomTom unavailable
        - Returns empty results on error (graceful degradation)
    """
    service = ShopDiscoveryService(db)

    try:
        results = await service.search_nearby_shops(
            latitude=search_request.latitude,
            longitude=search_request.longitude,
            radius_meters=search_request.radius_meters,
            shop_type=search_request.shop_type or "auto",
        )

        # Determine which source was used
        source = results[0]["source"] if results else "none"

        return ShopSearchResponse(
            results=[PlaceResult(**r) for r in results],
            count=len(results),
            source=source,
            latitude=search_request.latitude,
            longitude=search_request.longitude,
            radius_meters=search_request.radius_meters or 8000,
        )

    except Exception as e:
        logger.error("Shop search failed: %s", str(e))
        raise HTTPException(
            status_code=500, detail=f"Failed to search for shops: {str(e)}"
        )


@router.post("/save", response_model=AddressBookEntryResponse, status_code=201)
async def save_discovered_shop(
    entry_data: AddressBookEntryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Save a discovered shop to the address book.

    Args:
        entry_data: Address book entry data
        db: Database session
        current_user: Authenticated user

    Returns:
        Created AddressBookEntry

    Notes:
        - Shop source should be set to 'tomtom' or 'osm'
        - Category defaults to 'service'
    """
    # Create address book entry
    entry = AddressBookEntry(**entry_data.model_dump())

    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    logger.info("Saved discovered shop: %s", entry.business_name)

    return AddressBookEntryResponse.model_validate(entry)


@router.get("/recommendations", response_model=ShopRecommendationsResponse)
async def get_shop_recommendations(
    limit: int = 5,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Get recommended shops based on usage history.

    Args:
        limit: Maximum number of recommendations (default: 5)
        db: Database session
        current_user: Authenticated user

    Returns:
        ShopRecommendationsResponse with top shops by usage

    Notes:
        - Only returns shops with category='service'
        - Sorted by usage_count DESC (most used first)
        - Only includes shops that have been used at least once
    """
    # Get shops from address book sorted by usage_count
    query = (
        select(AddressBookEntry)
        .where(
            and_(
                AddressBookEntry.category == "service",
                AddressBookEntry.usage_count > 0,
            )
        )
        .order_by(AddressBookEntry.usage_count.desc())
        .limit(limit)
    )

    result = await db.execute(query)
    shops = result.scalars().all()

    recommendations = [
        ShopRecommendation(
            id=shop.id,
            business_name=shop.business_name,
            address=shop.address,
            city=shop.city,
            state=shop.state,
            phone=shop.phone,
            usage_count=shop.usage_count,
            rating=shop.rating,
            user_rating=shop.user_rating,
        )
        for shop in shops
    ]

    return ShopRecommendationsResponse(
        recommendations=recommendations,
        count=len(recommendations),
    )


@router.post("/increment-usage/{shop_id}", status_code=204)
async def increment_shop_usage(
    shop_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(require_auth),
):
    """Increment usage count for a shop.

    Called when creating service record with this shop.

    Args:
        shop_id: Address book entry ID
        db: Database session
        current_user: Authenticated user

    Returns:
        None (204 No Content)

    Raises:
        HTTPException: 404 if shop not found
    """
    result = await db.execute(
        select(AddressBookEntry).where(AddressBookEntry.id == shop_id)
    )
    shop = result.scalar_one_or_none()

    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    shop.usage_count += 1
    shop.last_used = datetime.now()

    await db.commit()

    logger.info(
        "Incremented usage for shop %s (now %d)", shop.business_name, shop.usage_count
    )

    return None

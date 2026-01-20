"""POI (Points of Interest) discovery service for finding nearby locations.

Supports multiple POI categories:
- Auto/RV repair shops
- EV charging stations
- Fuel stations

Uses multi-provider architecture with automatic fallback:
1. TomTom Places API (if configured)
2. OpenStreetMap Overpass API (always available)
3. Future: Google Places, Yelp, Foursquare, Geoapify (Phase 2)
"""

import logging
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.poi.base import POICategory
from app.services.poi.registry import POIProviderRegistry
from app.utils.logging_utils import sanitize_for_log, mask_coordinates

logger = logging.getLogger(__name__)


class POIDiscoveryService:
    """Service for discovering nearby Points of Interest across multiple categories.

    This service wraps the POIProviderRegistry and provides the main interface
    for POI searches. It handles:
    - Multi-category searches
    - Deduplication of results
    - Distance-based sorting
    - Provider selection and fallback
    """

    def __init__(self, db: AsyncSession):
        """Initialize POI discovery service.

        Args:
            db: Database session for loading settings
        """
        self.db = db
        self.registry = POIProviderRegistry(db)

    async def search_nearby_pois(
        self,
        latitude: float,
        longitude: float,
        radius_meters: int,
        categories: list[POICategory],
    ) -> tuple[list[dict[str, Any]], str]:
        """Search for POIs across multiple categories.

        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            radius_meters: Search radius in meters
            categories: List of POI categories to search for

        Returns:
            Tuple of (results, provider_used)
            - results: List of normalized POI dictionaries, sorted by distance
            - provider_used: Name of the provider that returned results
        """
        logger.info(
            "Searching for POIs near (%s) within %dm, categories: %s",
            mask_coordinates(latitude, longitude),
            radius_meters,
            [sanitize_for_log(c.value) for c in categories],
        )

        # Search using provider registry with automatic fallback
        results, provider_used = await self.registry.search_multi_category(
            latitude, longitude, radius_meters, categories
        )

        # Sort by distance (closest first)
        # Some providers return distance_meters, others don't
        results.sort(key=lambda x: x.get("distance_meters", float("inf")))

        logger.info(
            "Found %d POIs using provider: %s",
            len(results),
            sanitize_for_log(provider_used),
        )

        return results, provider_used


# Backward compatibility: Keep ShopDiscoveryService as alias
# This allows old code to continue working without changes
# TODO: Remove in version 2.0.0
class ShopDiscoveryService:
    """Legacy shop discovery service (backward compatibility only).

    DEPRECATED: Use POIDiscoveryService instead.
    This class is maintained for backward compatibility and will be removed
    in version 2.0.0.
    """

    def __init__(self, db: AsyncSession):
        """Initialize legacy shop discovery service.

        Args:
            db: Database session
        """
        logger.warning(
            "ShopDiscoveryService is deprecated, use POIDiscoveryService instead"
        )
        self.db = db
        self._poi_service = POIDiscoveryService(db)

    async def search_nearby_shops(
        self,
        latitude: float,
        longitude: float,
        radius_meters: int = 8000,
        shop_type: str = "auto",
    ) -> list[dict[str, Any]]:
        """Search for repair shops near coordinates (legacy interface).

        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            radius_meters: Search radius (default: 8000m)
            shop_type: Type of shop ('auto' or 'rv')

        Returns:
            List of PlaceResult dictionaries (normalized format)
        """
        # Map shop_type to POI categories
        if shop_type == "rv":
            categories = [POICategory.RV_SHOP]
        else:
            categories = [POICategory.AUTO_SHOP]

        # Call new POI service
        results, _ = await self._poi_service.search_nearby_pois(
            latitude, longitude, radius_meters, categories
        )

        return results

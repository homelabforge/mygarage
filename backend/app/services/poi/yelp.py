"""Yelp Fusion API provider for POI search."""

import logging
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import httpx

from app.services.poi.base import BasePOIProvider, POICategory

logger = logging.getLogger(__name__)


def validate_yelp_url(url: str) -> None:
    """Validate Yelp Fusion API URL to prevent SSRF attacks.

    Args:
        url: URL to validate

    Raises:
        ValueError: If URL is not a valid Yelp Fusion API endpoint
    """
    allowed_hosts = ["api.yelp.com"]
    parsed = urlparse(url)
    if parsed.hostname not in allowed_hosts:
        raise ValueError(f"Invalid Yelp Fusion API URL: {url}")


class YelpProvider(BasePOIProvider):
    """Yelp Fusion API provider.

    Features:
        - Consumer review data and ratings
        - Free tier: 5,000 requests/day
        - Supports: Auto shops, RV shops, EV charging, Fuel stations
        - Includes ratings and review counts
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.yelp.com/v3/businesses/search",
    ):
        """Initialize Yelp provider.

        Args:
            api_key: Yelp Fusion API key
            base_url: Yelp Fusion API base URL
        """
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = 30.0
        self.max_results = 20

        # Validate base URL for SSRF protection
        try:
            validate_yelp_url(self.base_url)
        except ValueError as e:
            logger.error("Invalid Yelp Fusion base URL: %s - %s", self.base_url, str(e))
            raise

    async def search(
        self,
        latitude: float,
        longitude: float,
        radius_meters: int,
        categories: list[POICategory],
    ) -> list[dict[str, Any]]:
        """Search Yelp Fusion API for POIs.

        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            radius_meters: Search radius in meters (max 40000)
            categories: List of POI categories to search for

        Returns:
            List of normalized POI results
        """
        all_results = []

        # Yelp has a max radius of 40,000 meters
        radius_meters = min(radius_meters, 40000)

        for category in categories:
            try:
                if category == POICategory.AUTO_SHOP:
                    results = await self._search_auto_shops(
                        latitude, longitude, radius_meters
                    )
                    all_results.extend(results)
                elif category == POICategory.RV_SHOP:
                    results = await self._search_rv_shops(
                        latitude, longitude, radius_meters
                    )
                    all_results.extend(results)
                elif category == POICategory.EV_CHARGING:
                    results = await self._search_ev_charging(
                        latitude, longitude, radius_meters
                    )
                    all_results.extend(results)
                elif category == POICategory.FUEL_STATION:
                    results = await self._search_fuel_stations(
                        latitude, longitude, radius_meters
                    )
                    all_results.extend(results)
            except Exception as e:
                logger.warning(
                    "Yelp search failed for category %s: %s", category.value, str(e)
                )
                continue

        return all_results

    async def _search_auto_shops(
        self, latitude: float, longitude: float, radius_meters: int
    ) -> list[dict[str, Any]]:
        """Search for auto repair shops."""
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "radius": radius_meters,
            "categories": "autorepair",
            "limit": self.max_results,
        }
        return await self._execute_search(params, POICategory.AUTO_SHOP)

    async def _search_rv_shops(
        self, latitude: float, longitude: float, radius_meters: int
    ) -> list[dict[str, Any]]:
        """Search for RV repair shops."""
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "radius": radius_meters,
            "categories": "rvrepair",
            "limit": self.max_results,
        }
        return await self._execute_search(params, POICategory.RV_SHOP)

    async def _search_ev_charging(
        self, latitude: float, longitude: float, radius_meters: int
    ) -> list[dict[str, Any]]:
        """Search for EV charging stations."""
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "radius": radius_meters,
            "categories": "evcstation",
            "limit": self.max_results,
        }
        return await self._execute_search(params, POICategory.EV_CHARGING)

    async def _search_fuel_stations(
        self, latitude: float, longitude: float, radius_meters: int
    ) -> list[dict[str, Any]]:
        """Search for fuel/gas stations."""
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "radius": radius_meters,
            "categories": "servicestations",
            "limit": self.max_results,
        }
        return await self._execute_search(params, POICategory.FUEL_STATION)

    async def _execute_search(
        self, params: dict, category: POICategory
    ) -> list[dict[str, Any]]:
        """Execute search request to Yelp Fusion API."""
        headers = {"Authorization": f"Bearer {self.api_key}"}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                # codeql[py/partial-ssrf] - self.base_url validated in __init__
                response = await client.get(
                    self.base_url, params=params, headers=headers
                )
                response.raise_for_status()
                data = response.json()

                businesses = data.get("businesses", [])
                return [self.normalize_result(b, category) for b in businesses]

            except httpx.TimeoutException:
                logger.error("Yelp API timeout for category %s", category.value)
                raise
            except httpx.HTTPStatusError as e:
                logger.error(
                    "Yelp API error for category %s: %s", category.value, str(e)
                )
                raise

    def normalize_result(
        self, raw_result: dict, category: POICategory = None
    ) -> dict[str, Any]:
        """Normalize Yelp result to common format.

        Args:
            raw_result: Raw Yelp Fusion API response
            category: POI category (required)

        Returns:
            Normalized POI result dictionary
        """
        location = raw_result.get("location", {})
        coordinates = raw_result.get("coordinates", {})

        # Yelp doesn't provide detailed metadata for EV/fuel
        metadata = None

        return {
            "business_name": raw_result.get("name") or "Unknown",
            "address": location.get("address1"),
            "city": location.get("city"),
            "state": location.get("state"),
            "zip_code": location.get("zip_code"),
            "phone": raw_result.get("phone"),
            "latitude": Decimal(str(coordinates.get("latitude")))
            if coordinates.get("latitude")
            else None,
            "longitude": Decimal(str(coordinates.get("longitude")))
            if coordinates.get("longitude")
            else None,
            "source": "yelp",
            "external_id": raw_result.get("id"),
            "rating": Decimal(str(raw_result.get("rating")))
            if raw_result.get("rating")
            else None,
            "distance_meters": raw_result.get("distance"),  # Yelp provides this
            "website": raw_result.get("url"),  # Yelp business page URL
            "poi_category": category.value if category else None,
            "metadata": metadata,
        }

    @property
    def provider_name(self) -> str:
        """Provider name."""
        return "yelp"

    @property
    def requires_api_key(self) -> bool:
        """Yelp requires an API key."""
        return True

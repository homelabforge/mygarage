"""Foursquare Places API provider for POI search."""

import logging
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import httpx

from app.services.poi.base import BasePOIProvider, POICategory

logger = logging.getLogger(__name__)


def validate_foursquare_url(url: str) -> None:
    """Validate Foursquare Places API URL to prevent SSRF attacks.

    Args:
        url: URL to validate

    Raises:
        ValueError: If URL is not a valid Foursquare Places API endpoint
    """
    allowed_hosts = ["api.foursquare.com"]
    parsed = urlparse(url)
    if parsed.hostname not in allowed_hosts:
        raise ValueError(f"Invalid Foursquare Places API URL: {url}")


class FoursquareProvider(BasePOIProvider):
    """Foursquare Places API v3 provider.

    Features:
        - Rich venue data and recommendations
        - Supports: Auto shops, RV shops, EV charging, Fuel stations
        - Includes ratings and venue details
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.foursquare.com/v3/places/search",
    ):
        """Initialize Foursquare provider.

        Args:
            api_key: Foursquare Places API key
            base_url: Foursquare Places API base URL
        """
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = 30.0
        self.max_results = 20

        # Validate base URL for SSRF protection
        try:
            validate_foursquare_url(self.base_url)
        except ValueError as e:
            logger.error("Invalid Foursquare base URL: %s - %s", self.base_url, str(e))
            raise

    async def search(
        self,
        latitude: float,
        longitude: float,
        radius_meters: int,
        categories: list[POICategory],
    ) -> list[dict[str, Any]]:
        """Search Foursquare Places API for POIs.

        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            radius_meters: Search radius in meters
            categories: List of POI categories to search for

        Returns:
            List of normalized POI results
        """
        all_results = []

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
                    "Foursquare search failed for category %s: %s",
                    category.value,
                    str(e),
                )
                continue

        return all_results

    async def _search_auto_shops(
        self, latitude: float, longitude: float, radius_meters: int
    ) -> list[dict[str, Any]]:
        """Search for auto repair shops using Foursquare category ID."""
        params = {
            "ll": f"{latitude},{longitude}",
            "radius": radius_meters,
            "categories": "17013",  # Automotive Services
            "limit": self.max_results,
        }
        return await self._execute_search(params, POICategory.AUTO_SHOP)

    async def _search_rv_shops(
        self, latitude: float, longitude: float, radius_meters: int
    ) -> list[dict[str, Any]]:
        """Search for RV parks using Foursquare category ID."""
        params = {
            "ll": f"{latitude},{longitude}",
            "radius": radius_meters,
            "categories": "19014",  # RV Parks
            "limit": self.max_results,
        }
        return await self._execute_search(params, POICategory.RV_SHOP)

    async def _search_ev_charging(
        self, latitude: float, longitude: float, radius_meters: int
    ) -> list[dict[str, Any]]:
        """Search for EV charging stations using Foursquare category ID."""
        params = {
            "ll": f"{latitude},{longitude}",
            "radius": radius_meters,
            "categories": "17069",  # Electric Vehicle Charging Station
            "limit": self.max_results,
        }
        return await self._execute_search(params, POICategory.EV_CHARGING)

    async def _search_fuel_stations(
        self, latitude: float, longitude: float, radius_meters: int
    ) -> list[dict[str, Any]]:
        """Search for fuel stations using Foursquare category ID."""
        params = {
            "ll": f"{latitude},{longitude}",
            "radius": radius_meters,
            "categories": "17069",  # Gas Station
            "limit": self.max_results,
        }
        return await self._execute_search(params, POICategory.FUEL_STATION)

    async def _execute_search(
        self, params: dict, category: POICategory
    ) -> list[dict[str, Any]]:
        """Execute search request to Foursquare Places API."""
        # Foursquare uses Authorization header without "Bearer" prefix
        headers = {"Authorization": self.api_key}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                # codeql[py/partial-ssrf] - self.base_url validated in __init__
                response = await client.get(
                    self.base_url, params=params, headers=headers
                )
                response.raise_for_status()
                data = response.json()

                results = data.get("results", [])
                return [self.normalize_result(r, category) for r in results]

            except httpx.TimeoutException:
                logger.error("Foursquare API timeout for category %s", category.value)
                raise
            except httpx.HTTPStatusError as e:
                logger.error(
                    "Foursquare API error for category %s: %s", category.value, str(e)
                )
                raise

    def normalize_result(
        self, raw_result: dict, category: POICategory = None
    ) -> dict[str, Any]:
        """Normalize Foursquare result to common format.

        Args:
            raw_result: Raw Foursquare Places API response
            category: POI category (required)

        Returns:
            Normalized POI result dictionary
        """
        location = raw_result.get("location", {})
        geocodes = raw_result.get("geocodes", {})
        main_geocode = geocodes.get("main", {})

        # Foursquare doesn't provide detailed EV/fuel metadata
        metadata = None

        return {
            "business_name": raw_result.get("name") or "Unknown",
            "address": location.get("formatted_address"),
            "city": location.get("locality"),
            "state": location.get("region"),
            "zip_code": location.get("postcode"),
            "phone": None,  # Not included in basic search
            "latitude": Decimal(str(main_geocode.get("latitude")))
            if main_geocode.get("latitude")
            else None,
            "longitude": Decimal(str(main_geocode.get("longitude")))
            if main_geocode.get("longitude")
            else None,
            "source": "foursquare",
            "external_id": raw_result.get("fsq_id"),
            "rating": Decimal(str(raw_result.get("rating")))
            if raw_result.get("rating")
            else None,
            "distance_meters": raw_result.get("distance"),  # Foursquare provides this
            "website": raw_result.get("website"),
            "poi_category": category.value if category else None,
            "metadata": metadata,
        }

    @property
    def provider_name(self) -> str:
        """Provider name."""
        return "foursquare"

    @property
    def requires_api_key(self) -> bool:
        """Foursquare requires an API key."""
        return True

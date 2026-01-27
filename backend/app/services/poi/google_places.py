"""Google Places API provider for POI search."""

import logging
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import httpx

from app.services.poi.base import BasePOIProvider, POICategory

logger = logging.getLogger(__name__)


def validate_google_url(url: str) -> None:
    """Validate Google Places API URL to prevent SSRF attacks.

    Args:
        url: URL to validate

    Raises:
        ValueError: If URL is not a valid Google Places API endpoint
    """
    allowed_hosts = ["maps.googleapis.com"]
    parsed = urlparse(url)
    if parsed.hostname not in allowed_hosts:
        raise ValueError(f"Invalid Google Places API URL: {url}")


class GooglePlacesProvider(BasePOIProvider):
    """Google Places API provider.

    Features:
        - High-quality commercial data
        - Comprehensive POI coverage
        - Supports: Auto shops, RV shops, EV charging, Fuel stations
        - Requires API key with Places API enabled
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://maps.googleapis.com/maps/api/place/nearbysearch/json",
    ):
        """Initialize Google Places provider.

        Args:
            api_key: Google Places API key
            base_url: Google Places API base URL
        """
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = 30.0
        self.max_results = 20

        # Validate base URL for SSRF protection
        try:
            validate_google_url(self.base_url)
        except ValueError as e:
            logger.error("Invalid Google Places base URL: %s - %s", self.base_url, str(e))
            raise

    async def search(
        self,
        latitude: float,
        longitude: float,
        radius_meters: int,
        categories: list[POICategory],
    ) -> list[dict[str, Any]]:
        """Search Google Places API for POIs.

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
                    results = await self._search_auto_shops(latitude, longitude, radius_meters)
                    all_results.extend(results)
                elif category == POICategory.RV_SHOP:
                    results = await self._search_rv_shops(latitude, longitude, radius_meters)
                    all_results.extend(results)
                elif category == POICategory.EV_CHARGING:
                    results = await self._search_ev_charging(latitude, longitude, radius_meters)
                    all_results.extend(results)
                elif category == POICategory.FUEL_STATION:
                    results = await self._search_fuel_stations(latitude, longitude, radius_meters)
                    all_results.extend(results)
            except Exception as e:
                logger.warning(
                    "Google Places search failed for category %s: %s",
                    category.value,
                    str(e),
                )
                continue

        return all_results

    async def _search_auto_shops(
        self, latitude: float, longitude: float, radius_meters: int
    ) -> list[dict[str, Any]]:
        """Search for auto repair shops."""
        params = {
            "location": f"{latitude},{longitude}",
            "radius": radius_meters,
            "type": "car_repair",
            "key": self.api_key,
        }
        return await self._execute_search(params, POICategory.AUTO_SHOP)

    async def _search_rv_shops(
        self, latitude: float, longitude: float, radius_meters: int
    ) -> list[dict[str, Any]]:
        """Search for RV parks/repair."""
        params = {
            "location": f"{latitude},{longitude}",
            "radius": radius_meters,
            "type": "rv_park",
            "key": self.api_key,
        }
        return await self._execute_search(params, POICategory.RV_SHOP)

    async def _search_ev_charging(
        self, latitude: float, longitude: float, radius_meters: int
    ) -> list[dict[str, Any]]:
        """Search for EV charging stations."""
        params = {
            "location": f"{latitude},{longitude}",
            "radius": radius_meters,
            "type": "electric_vehicle_charging_station",
            "key": self.api_key,
        }
        return await self._execute_search(params, POICategory.EV_CHARGING)

    async def _search_fuel_stations(
        self, latitude: float, longitude: float, radius_meters: int
    ) -> list[dict[str, Any]]:
        """Search for fuel/gas stations."""
        params = {
            "location": f"{latitude},{longitude}",
            "radius": radius_meters,
            "type": "gas_station",
            "key": self.api_key,
        }
        return await self._execute_search(params, POICategory.FUEL_STATION)

    async def _execute_search(self, params: dict, category: POICategory) -> list[dict[str, Any]]:
        """Execute search request to Google Places API."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                # codeql[py/partial-ssrf] - self.base_url validated in __init__
                response = await client.get(self.base_url, params=params)
                response.raise_for_status()
                data = response.json()

                status = data.get("status")
                if status not in ["OK", "ZERO_RESULTS"]:
                    error_msg = data.get("error_message", "Unknown error")
                    logger.error("Google Places API error: %s", error_msg)
                    return []

                results = data.get("results", [])
                return [self.normalize_result(r, category) for r in results[: self.max_results]]

            except httpx.TimeoutException:
                logger.error("Google Places API timeout for category %s", category.value)
                raise
            except httpx.HTTPStatusError as e:
                logger.error(
                    "Google Places API error for category %s: %s",
                    category.value,
                    str(e),
                )
                raise

    def normalize_result(self, raw_result: dict, category: POICategory = None) -> dict[str, Any]:
        """Normalize Google Places result to common format.

        Args:
            raw_result: Raw Google Places API response
            category: POI category (required)

        Returns:
            Normalized POI result dictionary
        """
        geometry = raw_result.get("geometry", {})
        location = geometry.get("location", {})

        # Build metadata based on category
        metadata = None
        if category == POICategory.EV_CHARGING:
            # Google Places doesn't provide detailed EV charging info in basic search
            metadata = {
                "connector_types": [],
                "charging_speeds": [],
                "network": None,
                "availability": None,
            }
        elif category == POICategory.FUEL_STATION:
            # Google Places doesn't provide fuel prices in basic search
            metadata = {
                "prices": {},
                "price_updated_at": None,
                "fuel_types": [],
            }

        return {
            "business_name": raw_result.get("name") or "Unknown",
            "address": raw_result.get("vicinity"),  # Short address format
            "city": None,  # Not provided in basic search
            "state": None,  # Not provided in basic search
            "zip_code": None,  # Not provided in basic search
            "phone": None,  # Requires Place Details API (separate call)
            "latitude": Decimal(str(location.get("lat"))) if location.get("lat") else None,
            "longitude": Decimal(str(location.get("lng"))) if location.get("lng") else None,
            "source": "google_places",
            "external_id": raw_result.get("place_id"),
            "rating": Decimal(str(raw_result.get("rating"))) if raw_result.get("rating") else None,
            "distance_meters": None,  # Not included in response, could calculate
            "website": None,  # Requires Place Details API
            "poi_category": category.value if category else None,
            "metadata": metadata,
        }

    @property
    def provider_name(self) -> str:
        """Provider name."""
        return "google_places"

    @property
    def requires_api_key(self) -> bool:
        """Google Places requires an API key."""
        return True

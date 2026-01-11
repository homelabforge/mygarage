"""TomTom Places API provider for POI search."""

import logging
from typing import Any
from decimal import Decimal
import httpx

from app.services.poi.base import BasePOIProvider, POICategory
from app.utils.url_validation import validate_tomtom_url
from app.exceptions import SSRFProtectionError

logger = logging.getLogger(__name__)


class TomTomProvider(BasePOIProvider):
    """TomTom Places API provider.

    Features:
        - High-quality commercial data
        - Free tier: 2,500 requests/day
        - Supports: Auto shops, RV shops, EV charging, Gas stations, Propane
    """

    def __init__(self, api_key: str, base_url: str = "https://api.tomtom.com/search/2"):
        """Initialize TomTom provider.

        Args:
            api_key: TomTom API key
            base_url: TomTom Search API base URL
        """
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = 30.0
        self.max_results = 20

        # Validate base URL for SSRF protection
        try:
            validate_tomtom_url(self.base_url)
        except (SSRFProtectionError, ValueError) as e:
            logger.error(
                "SSRF protection blocked TomTom base URL: %s - %s",
                self.base_url,
                str(e),
            )
            raise

    async def search(
        self,
        latitude: float,
        longitude: float,
        radius_meters: int,
        categories: list[POICategory],
    ) -> list[dict[str, Any]]:
        """Search TomTom Places API for POIs.

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
                elif category == POICategory.GAS_STATION:
                    results = await self._search_gas_stations(
                        latitude, longitude, radius_meters
                    )
                    all_results.extend(results)
                elif category == POICategory.PROPANE:
                    results = await self._search_propane(
                        latitude, longitude, radius_meters
                    )
                    all_results.extend(results)
            except Exception as e:
                logger.warning(
                    "TomTom search failed for category %s: %s", category.value, str(e)
                )
                continue

        return all_results

    async def _search_auto_shops(
        self, latitude: float, longitude: float, radius_meters: int
    ) -> list[dict[str, Any]]:
        """Search for auto repair shops."""
        url = f"{self.base_url}/categorySearch/auto repair.json"
        params = {
            "key": self.api_key,
            "lat": latitude,
            "lon": longitude,
            "radius": radius_meters,
            "limit": self.max_results,
        }
        return await self._execute_search(url, params, POICategory.AUTO_SHOP)

    async def _search_rv_shops(
        self, latitude: float, longitude: float, radius_meters: int
    ) -> list[dict[str, Any]]:
        """Search for RV repair shops using fuzzy search."""
        url = f"{self.base_url}/search/RV repair.json"
        params = {
            "key": self.api_key,
            "lat": latitude,
            "lon": longitude,
            "radius": radius_meters,
            "limit": self.max_results,
            "typeahead": False,
        }
        return await self._execute_search(url, params, POICategory.RV_SHOP)

    async def _search_ev_charging(
        self, latitude: float, longitude: float, radius_meters: int
    ) -> list[dict[str, Any]]:
        """Search for EV charging stations."""
        url = f"{self.base_url}/categorySearch/electric vehicle charging station.json"
        params = {
            "key": self.api_key,
            "lat": latitude,
            "lon": longitude,
            "radius": radius_meters,
            "limit": self.max_results,
        }
        return await self._execute_search(url, params, POICategory.EV_CHARGING)

    async def _search_gas_stations(
        self, latitude: float, longitude: float, radius_meters: int
    ) -> list[dict[str, Any]]:
        """Search for gas stations."""
        url = f"{self.base_url}/categorySearch/petrol station.json"
        params = {
            "key": self.api_key,
            "lat": latitude,
            "lon": longitude,
            "radius": radius_meters,
            "limit": self.max_results,
        }
        return await self._execute_search(url, params, POICategory.GAS_STATION)

    async def _search_propane(
        self, latitude: float, longitude: float, radius_meters: int
    ) -> list[dict[str, Any]]:
        """Search for propane stations."""
        url = f"{self.base_url}/search/propane.json"
        params = {
            "key": self.api_key,
            "lat": latitude,
            "lon": longitude,
            "radius": radius_meters,
            "limit": self.max_results,
            "typeahead": False,
        }
        return await self._execute_search(url, params, POICategory.PROPANE)

    async def _execute_search(
        self, url: str, params: dict, category: POICategory
    ) -> list[dict[str, Any]]:
        """Execute search request to TomTom API."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                # codeql[py/partial-ssrf] - self.base_url validated in __init__
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                results = data.get("results", [])
                return [self.normalize_result(r, category) for r in results]

            except httpx.TimeoutException:
                logger.error("TomTom API timeout for category %s", category.value)
                raise
            except httpx.HTTPStatusError as e:
                logger.error(
                    "TomTom API error for category %s: %s", category.value, str(e)
                )
                raise

    def normalize_result(
        self, raw_result: dict, category: POICategory = None
    ) -> dict[str, Any]:
        """Normalize TomTom result to common format."""
        poi = raw_result.get("poi", {})
        address = raw_result.get("address", {})
        position = raw_result.get("position", {})

        # Build address string
        address_parts = []
        if address.get("streetNumber") and address.get("streetName"):
            address_parts.append(f"{address['streetNumber']} {address['streetName']}")
        elif address.get("streetName"):
            address_parts.append(address["streetName"])

        # Extract POI category from raw result if not provided
        if category is None:
            # Try to infer from TomTom categories
            categories = poi.get("categories", [])
            if any(
                "repair" in cat.lower() or "garage" in cat.lower() for cat in categories
            ):
                category = POICategory.AUTO_SHOP
            elif any("charging" in cat.lower() for cat in categories):
                category = POICategory.EV_CHARGING
            elif any(
                "petrol" in cat.lower() or "gas" in cat.lower() for cat in categories
            ):
                category = POICategory.GAS_STATION
            elif any("propane" in cat.lower() for cat in categories):
                category = POICategory.PROPANE
            else:
                category = POICategory.AUTO_SHOP  # Default

        # Build metadata based on category
        metadata = None
        if category == POICategory.EV_CHARGING:
            # TomTom may include EV charging data in extended response
            metadata = {
                "connector_types": [],  # TomTom doesn't provide this in basic search
                "charging_speeds": [],
                "network": None,
                "availability": None,
            }

        return {
            "business_name": poi.get("name") or "Unknown",
            "address": address_parts[0] if address_parts else None,
            "city": address.get("municipality")
            or address.get("municipalitySubdivision"),
            "state": address.get("countrySubdivision"),
            "zip_code": address.get("postalCode"),
            "phone": poi.get("phone"),
            "latitude": Decimal(str(position.get("lat")))
            if position.get("lat")
            else None,
            "longitude": Decimal(str(position.get("lon")))
            if position.get("lon")
            else None,
            "source": "tomtom",
            "external_id": raw_result.get("id"),
            "rating": None,  # TomTom doesn't provide ratings in free tier
            "distance_meters": raw_result.get("dist"),
            "website": None,  # Not included in category search
            "poi_category": category.value,
            "metadata": metadata,
        }

    @property
    def provider_name(self) -> str:
        """Provider name."""
        return "tomtom"

    @property
    def requires_api_key(self) -> bool:
        """TomTom requires an API key."""
        return True

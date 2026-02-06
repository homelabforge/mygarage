"""Shop discovery service using TomTom API (primary) and OSM Overpass (fallback)."""

import logging
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.exceptions import SSRFProtectionError
from app.services.settings_service import SettingsService
from app.utils.logging_utils import mask_api_key, mask_coordinates, sanitize_for_log
from app.utils.url_validation import validate_tomtom_url

logger = logging.getLogger(__name__)


class ShopDiscoveryService:
    """Service for discovering nearby auto repair shops.

    Strategy:
        1. Try TomTom Places API first (if API key configured)
        2. Fallback to OpenStreetMap Overpass API on error or missing key

    Security:
        - Validates TomTom API URLs against SSRF attacks
        - OSM Overpass endpoint is public, no validation needed
        - Blocks private IPs for TomTom requests

    Features:
        - TomTom: High-quality commercial data (2,500 free requests/day)
        - OSM: Unlimited free fallback (crowd-sourced, varies by region)
    """

    def __init__(self, db: AsyncSession):
        """Initialize shop discovery service.

        Args:
            db: Database session for loading settings
        """
        self.db = db

        # Will be populated by _load_settings()
        self.tomtom_api_key: str = ""
        self.tomtom_enabled: bool = False
        self.tomtom_base_url: str = app_settings.tomtom_api_base_url

        # OpenStreetMap Overpass API (public endpoint, no API key needed)
        # Using multiple instances for redundancy (public instances can be overloaded)
        self.osm_overpass_urls = [
            "https://overpass.kumi.systems/api/interpreter",  # Primary (Kumi Systems - reliable)
            "https://overpass-api.de/api/interpreter",  # Fallback 1 (official)
            "https://overpass.openstreetmap.fr/api/interpreter",  # Fallback 2 (French)
        ]

        self.timeout = 30.0
        self.search_radius = app_settings.shop_search_radius_meters
        self.max_results = app_settings.shop_search_max_results

    async def _load_settings(self) -> None:
        """Load TomTom settings from database."""
        # Get tomtom_enabled setting
        enabled_setting = await SettingsService.get(self.db, "tomtom_enabled")
        tomtom_enabled_str = (enabled_setting.value or "false") if enabled_setting else "false"

        # Get tomtom_api_key setting
        key_setting = await SettingsService.get(self.db, "tomtom_api_key")
        self.tomtom_api_key = (key_setting.value or "") if key_setting else ""

        # Enable TomTom only if both settings are set correctly
        self.tomtom_enabled = tomtom_enabled_str.lower() == "true" and bool(self.tomtom_api_key)

        if self.tomtom_enabled:
            logger.info(
                "TomTom API enabled with key: %s",
                mask_api_key(self.tomtom_api_key),
            )
            try:
                validate_tomtom_url(self.tomtom_base_url)
                logger.info(
                    "TomTom base URL validated: %s",
                    sanitize_for_log(self.tomtom_base_url),
                )
            except (SSRFProtectionError, ValueError) as e:
                logger.error(
                    "SSRF protection blocked TomTom base URL: %s - %s",
                    sanitize_for_log(self.tomtom_base_url),
                    sanitize_for_log(e),
                )
                # Disable TomTom if URL validation fails
                self.tomtom_enabled = False
                logger.warning("TomTom API disabled due to invalid base URL")
        else:
            logger.info(
                "TomTom API disabled (enabled=%s, has_key=%s)",
                tomtom_enabled_str,
                bool(self.tomtom_api_key),
            )

    async def search_nearby_shops(
        self,
        latitude: float,
        longitude: float,
        radius_meters: int | None = None,
        shop_type: str = "auto",
    ) -> list[dict[str, Any]]:
        """Search for repair shops near coordinates.

        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            radius_meters: Search radius (default: from settings)
            shop_type: Type of shop ('auto' or 'rv')

        Returns:
            List of PlaceResult dictionaries (normalized format)
        """
        # Load settings from database on each search (ensures fresh config)
        await self._load_settings()

        radius = radius_meters or self.search_radius

        # Try TomTom first (if enabled)
        if self.tomtom_enabled:
            try:
                logger.info(
                    "Searching TomTom for %s shops near (%s) within %sm",
                    sanitize_for_log(shop_type),
                    mask_coordinates(latitude, longitude),
                    radius,
                )
                results = await self._search_tomtom(latitude, longitude, radius, shop_type)
                logger.info("TomTom returned %d results", len(results))
                return results
            except Exception as e:
                logger.warning("TomTom search failed: %s, falling back to OSM", sanitize_for_log(e))

        # Fallback to OSM Overpass
        logger.info(
            "Searching OSM Overpass for %s shops near (%s) within %sm",
            sanitize_for_log(shop_type),
            mask_coordinates(latitude, longitude),
            radius,
        )
        results = await self._search_osm_overpass(latitude, longitude, radius, shop_type)
        logger.info("OSM Overpass returned %d results", len(results))
        return results

    async def _search_tomtom(
        self,
        latitude: float,
        longitude: float,
        radius_meters: int,
        shop_type: str = "auto",
    ) -> list[dict[str, Any]]:
        """Search TomTom Places API for repair shops.

        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            radius_meters: Search radius in meters
            shop_type: Type of shop ('auto' or 'rv')

        Returns:
            List of normalized PlaceResult dictionaries

        Raises:
            Exception: On API error (triggers fallback to OSM)
        """
        # TomTom Search API
        # Use Fuzzy Search for RV (more flexible text search)
        # Use Category Search for auto (more accurate POI categories)
        if shop_type == "rv":
            # Fuzzy Search: https://developer.tomtom.com/search-api/documentation/search-service/fuzzy-search
            # Allows free-text search for RV-specific terms
            search_query = "RV repair"
            url = f"{self.tomtom_base_url}/search/{search_query}.json"
            params = {
                "key": self.tomtom_api_key,
                "lat": latitude,
                "lon": longitude,
                "radius": radius_meters,
                "limit": self.max_results,
                "typeahead": False,
                # No categorySet filter - RV repair shops may be in various categories
            }
        else:
            # Category Search: https://developer.tomtom.com/search-api/documentation/search-service/category-search
            search_term = "auto repair"
            url = f"{self.tomtom_base_url}/categorySearch/{search_term}.json"
            params = {
                "key": self.tomtom_api_key,
                "lat": latitude,
                "lon": longitude,
                "radius": radius_meters,
                "limit": self.max_results,
            }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                # codeql[py/partial-ssrf] - self.tomtom_base_url validated in __init__
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                # Parse TomTom response
                results = data.get("results", [])

                return [self._normalize_tomtom_result(r) for r in results]

            except httpx.TimeoutException:
                logger.error("TomTom API timeout")
                raise
            except httpx.HTTPStatusError as e:
                logger.error("TomTom API error: %s", sanitize_for_log(e))
                raise

    async def _search_osm_overpass(
        self,
        latitude: float,
        longitude: float,
        radius_meters: int,
        shop_type: str = "auto",
    ) -> list[dict[str, Any]]:
        """Search OpenStreetMap Overpass API for repair shops.

        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            radius_meters: Search radius in meters
            shop_type: Type of shop ('auto' or 'rv')

        Returns:
            List of normalized PlaceResult dictionaries

        Raises:
            Exception: If all Overpass instances fail
        """
        # Overpass QL query for repair shops
        # Using multiple OSM tags to maximize results
        if shop_type == "rv":
            # RV repair: caravan shops, RV service centers
            query = f"""
            [out:json][timeout:25];
            (
              node["shop"="caravan"](around:{radius_meters},{latitude},{longitude});
              way["shop"="caravan"](around:{radius_meters},{latitude},{longitude});
              node["amenity"="vehicle_inspection"]["vehicle:type"="rv"](around:{radius_meters},{latitude},{longitude});
              way["amenity"="vehicle_inspection"]["vehicle:type"="rv"](around:{radius_meters},{latitude},{longitude});
            );
            out body;
            >;
            out skel qt;
            """
        else:
            # Auto repair: car_repair, car service, tire shops, oil change, mechanics
            query = f"""
            [out:json][timeout:25];
            (
              node["amenity"="car_repair"](around:{radius_meters},{latitude},{longitude});
              way["amenity"="car_repair"](around:{radius_meters},{latitude},{longitude});
              node["shop"="car_repair"](around:{radius_meters},{latitude},{longitude});
              way["shop"="car_repair"](around:{radius_meters},{latitude},{longitude});
              node["shop"="tyres"](around:{radius_meters},{latitude},{longitude});
              way["shop"="tyres"](around:{radius_meters},{latitude},{longitude});
              node["craft"="car_repair"](around:{radius_meters},{latitude},{longitude});
              way["craft"="car_repair"](around:{radius_meters},{latitude},{longitude});
            );
            out body;
            >;
            out skel qt;
            """

        # Try each Overpass instance until one succeeds
        last_error = None
        for instance_url in self.osm_overpass_urls:
            try:
                logger.info("Trying Overpass instance: %s", sanitize_for_log(instance_url))
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(instance_url, data={"data": query})
                    response.raise_for_status()
                    data = response.json()

                    # Parse OSM response
                    elements = data.get("elements", [])

                    # Filter and normalize results
                    results = []
                    for element in elements[: self.max_results]:
                        if element.get("type") in ["node", "way"]:
                            normalized = self._normalize_osm_result(element)
                            if normalized:
                                results.append(normalized)

                    logger.info(
                        "Successfully got %d results from %s",
                        len(results),
                        sanitize_for_log(instance_url),
                    )
                    return results

            except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                logger.warning(
                    "Overpass instance %s failed: %s",
                    sanitize_for_log(instance_url),
                    sanitize_for_log(e),
                )
                last_error = e
                # Continue to next instance

        # All instances failed
        logger.error("All Overpass instances failed")
        if last_error:
            raise last_error
        raise Exception("All Overpass API instances failed")

    def _normalize_tomtom_result(self, result: dict) -> dict[str, Any]:
        """Normalize TomTom result to common PlaceResult format.

        Args:
            result: Raw TomTom API result

        Returns:
            Normalized PlaceResult dictionary
        """
        poi = result.get("poi", {})
        address = result.get("address", {})
        position = result.get("position", {})

        # Build address string
        address_parts = []
        if address.get("streetNumber") and address.get("streetName"):
            address_parts.append(f"{address['streetNumber']} {address['streetName']}")
        elif address.get("streetName"):
            address_parts.append(address["streetName"])

        return {
            "business_name": poi.get("name") or "Unknown Shop",
            "address": address_parts[0] if address_parts else None,
            "city": address.get("municipality") or address.get("municipalitySubdivision"),
            "state": address.get("countrySubdivision"),
            "zip_code": address.get("postalCode"),
            "phone": poi.get("phone"),
            "latitude": Decimal(str(position.get("lat"))),
            "longitude": Decimal(str(position.get("lon"))),
            "source": "tomtom",
            "external_id": result.get("id"),
            "rating": None,  # TomTom doesn't provide ratings in free tier
            "distance_meters": result.get("dist"),
            "category": "service",
            "website": None,  # Not included in category search
        }

    def _normalize_osm_result(self, element: dict) -> dict[str, Any] | None:
        """Normalize OSM result to common PlaceResult format.

        Args:
            element: Raw OSM element

        Returns:
            Normalized PlaceResult dictionary or None if invalid
        """
        tags = element.get("tags", {})

        # Skip if no name
        name = tags.get("name")
        if not name:
            return None

        # Get coordinates (node has lat/lon directly, way needs center calculation)
        lat = element.get("lat")
        lon = element.get("lon")
        if not lat or not lon:
            # For ways, OSM returns separate lat/lon in additional elements
            # For simplicity, skip ways without direct coordinates
            return None

        # Parse address from OSM tags
        address_parts = []
        if tags.get("addr:housenumber") and tags.get("addr:street"):
            address_parts.append(f"{tags['addr:housenumber']} {tags['addr:street']}")
        elif tags.get("addr:street"):
            address_parts.append(tags["addr:street"])

        return {
            "business_name": name,
            "address": address_parts[0] if address_parts else None,
            "city": tags.get("addr:city"),
            "state": tags.get("addr:state"),
            "zip_code": tags.get("addr:postcode"),
            "phone": tags.get("phone") or tags.get("contact:phone"),
            "latitude": Decimal(str(lat)),
            "longitude": Decimal(str(lon)),
            "source": "osm",
            "external_id": f"osm-{element['type']}-{element['id']}",
            "rating": None,  # OSM doesn't provide ratings
            "distance_meters": None,  # Calculate client-side if needed
            "category": "service",
            "website": tags.get("website") or tags.get("contact:website"),
        }

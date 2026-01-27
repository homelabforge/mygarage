"""POI provider registry for managing multiple search providers with fallback."""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.poi.base import BasePOIProvider, POICategory
from app.services.poi.foursquare import FoursquareProvider
from app.services.poi.google_places import GooglePlacesProvider
from app.services.poi.osm import OSMProvider
from app.services.poi.tomtom import TomTomProvider
from app.services.poi.yelp import YelpProvider
from app.services.settings_service import SettingsService
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


class POIProviderRegistry:
    """Manages POI search provider registration and selection with fallback.

    Providers are tried in priority order until one succeeds. OSM is always
    available as the ultimate fallback since it requires no API key.
    """

    def __init__(self, db: AsyncSession):
        """Initialize provider registry.

        Args:
            db: Database session for loading settings
        """
        self.db = db
        self.providers: dict[str, BasePOIProvider] = {}

    async def _load_provider_configs(self) -> list[dict[str, Any]]:
        """Load provider configurations from database settings.

        Returns:
            List of provider configs with name, enabled status, priority, api_key
        """
        configs = []

        # Load TomTom configuration
        tomtom_enabled_setting = await SettingsService.get(self.db, "tomtom_enabled")
        tomtom_enabled = (
            tomtom_enabled_setting.value.lower() == "true" if tomtom_enabled_setting else False
        )

        tomtom_key_setting = await SettingsService.get(self.db, "tomtom_api_key")
        tomtom_api_key = tomtom_key_setting.value if tomtom_key_setting else ""

        if tomtom_enabled and tomtom_api_key:
            configs.append(
                {
                    "name": "tomtom",
                    "enabled": True,
                    "priority": 1,  # Try TomTom first
                    "api_key": tomtom_api_key,
                }
            )
            logger.info("TomTom provider configured with priority 1")

        # Load Google Places configuration
        google_enabled_setting = await SettingsService.get(self.db, "google_places_enabled")
        google_enabled = (
            google_enabled_setting.value.lower() == "true" if google_enabled_setting else False
        )

        google_key_setting = await SettingsService.get(self.db, "google_places_api_key")
        google_api_key = google_key_setting.value if google_key_setting else ""

        if google_enabled and google_api_key:
            configs.append(
                {
                    "name": "google_places",
                    "enabled": True,
                    "priority": 2,  # After TomTom, before Yelp
                    "api_key": google_api_key,
                }
            )
            logger.info("Google Places provider configured with priority 2")

        # Load Yelp configuration
        yelp_enabled_setting = await SettingsService.get(self.db, "yelp_enabled")
        yelp_enabled = (
            yelp_enabled_setting.value.lower() == "true" if yelp_enabled_setting else False
        )

        yelp_key_setting = await SettingsService.get(self.db, "yelp_api_key")
        yelp_api_key = yelp_key_setting.value if yelp_key_setting else ""

        if yelp_enabled and yelp_api_key:
            configs.append(
                {
                    "name": "yelp",
                    "enabled": True,
                    "priority": 3,  # After Google, before Foursquare
                    "api_key": yelp_api_key,
                }
            )
            logger.info("Yelp provider configured with priority 3")

        # Load Foursquare configuration
        foursquare_enabled_setting = await SettingsService.get(self.db, "foursquare_enabled")
        foursquare_enabled = (
            foursquare_enabled_setting.value.lower() == "true"
            if foursquare_enabled_setting
            else False
        )

        foursquare_key_setting = await SettingsService.get(self.db, "foursquare_api_key")
        foursquare_api_key = foursquare_key_setting.value if foursquare_key_setting else ""

        if foursquare_enabled and foursquare_api_key:
            configs.append(
                {
                    "name": "foursquare",
                    "enabled": True,
                    "priority": 4,  # After Yelp, before OSM
                    "api_key": foursquare_api_key,
                }
            )
            logger.info("Foursquare provider configured with priority 4")

        # OSM is always available as fallback (lowest priority)
        configs.append(
            {
                "name": "osm",
                "enabled": True,
                "priority": 99,  # Try OSM last
                "api_key": None,
            }
        )
        logger.info("OSM provider configured as fallback with priority 99")

        return configs

    async def _register_providers(self) -> None:
        """Register and initialize all enabled providers."""
        configs = await self._load_provider_configs()

        for config in configs:
            try:
                if config["name"] == "tomtom" and config["enabled"]:
                    provider = TomTomProvider(api_key=config["api_key"])
                    self.providers["tomtom"] = provider
                    logger.info("Registered TomTom provider")
                elif config["name"] == "google_places" and config["enabled"]:
                    provider = GooglePlacesProvider(api_key=config["api_key"])
                    self.providers["google_places"] = provider
                    logger.info("Registered Google Places provider")
                elif config["name"] == "yelp" and config["enabled"]:
                    provider = YelpProvider(api_key=config["api_key"])
                    self.providers["yelp"] = provider
                    logger.info("Registered Yelp provider")
                elif config["name"] == "foursquare" and config["enabled"]:
                    provider = FoursquareProvider(api_key=config["api_key"])
                    self.providers["foursquare"] = provider
                    logger.info("Registered Foursquare provider")
                elif config["name"] == "osm":
                    provider = OSMProvider()
                    self.providers["osm"] = provider
                    logger.info("Registered OSM provider")

            except Exception as e:
                logger.error(
                    "Failed to register provider %s: %s",
                    sanitize_for_log(config["name"]),
                    sanitize_for_log(e),
                )
                continue

    async def search_multi_category(
        self,
        latitude: float,
        longitude: float,
        radius_meters: int,
        categories: list[POICategory],
    ) -> tuple[list[dict], str]:
        """Search using configured providers with priority fallback.

        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            radius_meters: Search radius in meters
            categories: List of POI categories to search for

        Returns:
            Tuple of (results, provider_used)
            - results: List of normalized POI dictionaries
            - provider_used: Name of the provider that returned results
        """
        # Register providers (loads fresh config from database)
        await self._register_providers()

        # Load provider configs to get priority order
        provider_configs = await self._load_provider_configs()

        # Try each provider in priority order
        for config in sorted(provider_configs, key=lambda x: x["priority"]):
            if not config["enabled"]:
                continue

            provider = self.providers.get(config["name"])
            if not provider:
                logger.warning("Provider %s not registered, skipping", config["name"])
                continue

            try:
                logger.info(
                    "Trying provider %s (priority %d) for categories: %s",
                    provider.provider_name,
                    config["priority"],
                    [c.value for c in categories],
                )

                results = await provider.search(latitude, longitude, radius_meters, categories)

                if results:
                    logger.info(
                        "Provider %s returned %d results",
                        provider.provider_name,
                        len(results),
                    )

                    # Track provider usage (import here to avoid circular dependency)
                    try:
                        from app.services.provider_usage import (
                            increment_provider_usage,
                        )

                        await increment_provider_usage(self.db, provider.provider_name)
                    except Exception as e:
                        logger.warning(
                            "Failed to track usage for %s: %s",
                            sanitize_for_log(provider.provider_name),
                            sanitize_for_log(e),
                        )

                    return results, provider.provider_name
                else:
                    logger.info(
                        "Provider %s returned no results, trying next provider",
                        provider.provider_name,
                    )

            except Exception as e:
                logger.warning(
                    "Provider %s failed: %s, trying next provider",
                    sanitize_for_log(provider.provider_name),
                    sanitize_for_log(e),
                )
                continue

        # All providers failed or returned no results
        logger.warning("All providers failed or returned no results")
        return [], "none"

    def _deduplicate_results(self, results: list[dict]) -> list[dict]:
        """Deduplicate POI results by external_id or lat/lon proximity.

        Args:
            results: List of POI result dictionaries

        Returns:
            Deduplicated list of results
        """
        seen_ids = set()
        seen_coords = set()
        deduplicated = []

        for result in results:
            # Check external_id first
            external_id = result.get("external_id")
            if external_id and external_id in seen_ids:
                continue

            # Check lat/lon proximity (within ~10 meters)
            lat = result.get("latitude")
            lon = result.get("longitude")
            if lat and lon:
                # Round to 4 decimal places (~11 meters precision)
                coord_key = (round(float(lat), 4), round(float(lon), 4))
                if coord_key in seen_coords:
                    continue
                seen_coords.add(coord_key)

            if external_id:
                seen_ids.add(external_id)

            deduplicated.append(result)

        logger.info(
            "Deduplicated %d results down to %d unique POIs",
            len(results),
            len(deduplicated),
        )
        return deduplicated

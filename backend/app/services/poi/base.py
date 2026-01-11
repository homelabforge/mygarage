"""Base provider interface for POI search services."""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any


class POICategory(Enum):
    """Categories of Points of Interest."""

    AUTO_SHOP = "auto_shop"
    RV_SHOP = "rv_shop"
    EV_CHARGING = "ev_charging"
    GAS_STATION = "gas_station"
    PROPANE = "propane"


class BasePOIProvider(ABC):
    """Abstract base class for all POI search providers.

    Each provider (TomTom, Google Places, Yelp, OSM, etc.) implements this interface
    to provide a consistent API for searching Points of Interest across multiple
    categories.
    """

    @abstractmethod
    async def search(
        self,
        latitude: float,
        longitude: float,
        radius_meters: int,
        categories: list[POICategory],
    ) -> list[dict[str, Any]]:
        """Search for POIs near coordinates.

        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            radius_meters: Search radius in meters
            categories: List of POI categories to search for

        Returns:
            List of normalized POI results. Each result is a dictionary with:
            - business_name: str
            - address: Optional[str]
            - city: Optional[str]
            - state: Optional[str]
            - zip_code: Optional[str]
            - phone: Optional[str]
            - latitude: Decimal
            - longitude: Decimal
            - source: str (provider name)
            - external_id: Optional[str]
            - rating: Optional[Decimal]
            - distance_meters: Optional[float]
            - website: Optional[str]
            - poi_category: str
            - metadata: Optional[dict] (category-specific data)
        """
        pass

    @abstractmethod
    def normalize_result(self, raw_result: dict) -> dict[str, Any]:
        """Normalize provider-specific result to common format.

        Args:
            raw_result: Raw API response from the provider

        Returns:
            Normalized result dictionary matching the format described in search()
        """
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider identifier (e.g., 'tomtom', 'google', 'osm').

        Returns:
            Provider name as lowercase string
        """
        pass

    @property
    @abstractmethod
    def requires_api_key(self) -> bool:
        """Whether this provider requires an API key.

        Returns:
            True if API key is required, False otherwise (e.g., OSM is free)
        """
        pass

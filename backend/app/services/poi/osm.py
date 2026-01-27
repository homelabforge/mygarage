"""OpenStreetMap Overpass API provider for POI search."""

import logging
import math
from decimal import Decimal
from typing import Any

import httpx

from app.services.poi.base import BasePOIProvider, POICategory

logger = logging.getLogger(__name__)


class OSMProvider(BasePOIProvider):
    """OpenStreetMap Overpass API provider.

    Features:
        - Free and unlimited
        - Crowd-sourced data (quality varies by region)
        - Supports: Auto shops, RV shops, EV charging, Gas stations, Propane
        - Multiple fallback instances for reliability
    """

    def __init__(self):
        """Initialize OSM provider."""
        # Using multiple Overpass instances for redundancy
        self.overpass_urls = [
            "https://overpass.kumi.systems/api/interpreter",  # Primary (reliable)
            "https://overpass-api.de/api/interpreter",  # Fallback 1 (official)
            "https://overpass.openstreetmap.fr/api/interpreter",  # Fallback 2
        ]
        self.timeout = 30.0
        self.max_results = 100  # Increased to capture more results before distance sorting

    async def search(
        self,
        latitude: float,
        longitude: float,
        radius_meters: int,
        categories: list[POICategory],
    ) -> list[dict[str, Any]]:
        """Search OpenStreetMap for POIs.

        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            radius_meters: Search radius in meters
            categories: List of POI categories to search for

        Returns:
            List of normalized POI results
        """
        # Build Overpass QL query for all requested categories
        query = self._build_query(latitude, longitude, radius_meters, categories)

        # Try each Overpass instance until one succeeds
        last_error = None
        for instance_url in self.overpass_urls:
            try:
                logger.info("Trying Overpass instance: %s", instance_url)
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(instance_url, data={"data": query})
                    response.raise_for_status()
                    data = response.json()

                    # Parse OSM response
                    elements = data.get("elements", [])

                    # Filter and normalize results
                    results = []
                    for element in elements:
                        if element.get("type") in ["node", "way"]:
                            normalized = self.normalize_result(element)
                            if normalized:
                                # Calculate distance from search center
                                distance = self._calculate_distance(
                                    latitude,
                                    longitude,
                                    float(normalized["latitude"]),
                                    float(normalized["longitude"]),
                                )
                                normalized["distance_meters"] = distance
                                results.append(normalized)

                    # Sort by distance and limit results
                    results.sort(key=lambda x: x.get("distance_meters", float("inf")))
                    results = results[: self.max_results]

                    logger.info(
                        "Successfully got %d results from %s",
                        len(results),
                        instance_url,
                    )
                    return results

            except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                logger.warning("Overpass instance %s failed: %s", instance_url, str(e))
                last_error = e
                continue

        # All instances failed
        logger.error("All Overpass instances failed")
        if last_error:
            raise last_error
        raise Exception("All Overpass API instances failed")

    def _build_query(
        self,
        latitude: float,
        longitude: float,
        radius_meters: int,
        categories: list[POICategory],
    ) -> str:
        """Build Overpass QL query for multiple categories."""
        query_parts = []

        for category in categories:
            if category == POICategory.AUTO_SHOP:
                query_parts.extend(
                    [
                        f'node["amenity"="car_repair"](around:{radius_meters},{latitude},{longitude});',
                        f'way["amenity"="car_repair"](around:{radius_meters},{latitude},{longitude});',
                        f'node["shop"="car_repair"](around:{radius_meters},{latitude},{longitude});',
                        f'way["shop"="car_repair"](around:{radius_meters},{latitude},{longitude});',
                        f'node["shop"="tyres"](around:{radius_meters},{latitude},{longitude});',
                        f'way["shop"="tyres"](around:{radius_meters},{latitude},{longitude});',
                        f'node["craft"="car_repair"](around:{radius_meters},{latitude},{longitude});',
                        f'way["craft"="car_repair"](around:{radius_meters},{latitude},{longitude});',
                    ]
                )
            elif category == POICategory.RV_SHOP:
                query_parts.extend(
                    [
                        f'node["shop"="caravan"](around:{radius_meters},{latitude},{longitude});',
                        f'way["shop"="caravan"](around:{radius_meters},{latitude},{longitude});',
                        f'node["amenity"="vehicle_inspection"]["vehicle:type"="rv"](around:{radius_meters},{latitude},{longitude});',
                        f'way["amenity"="vehicle_inspection"]["vehicle:type"="rv"](around:{radius_meters},{latitude},{longitude});',
                    ]
                )
            elif category == POICategory.EV_CHARGING:
                query_parts.extend(
                    [
                        f'node["amenity"="charging_station"](around:{radius_meters},{latitude},{longitude});',
                        f'way["amenity"="charging_station"](around:{radius_meters},{latitude},{longitude});',
                    ]
                )
            elif category == POICategory.GAS_STATION:
                query_parts.extend(
                    [
                        f'node["amenity"="fuel"](around:{radius_meters},{latitude},{longitude});',
                        f'way["amenity"="fuel"](around:{radius_meters},{latitude},{longitude});',
                    ]
                )
            elif category == POICategory.PROPANE:
                query_parts.extend(
                    [
                        f'node["shop"="gas"]["gas"="lpg"](around:{radius_meters},{latitude},{longitude});',
                        f'way["shop"="gas"]["gas"="lpg"](around:{radius_meters},{latitude},{longitude});',
                        f'node["amenity"="fuel"]["fuel:lpg"="yes"](around:{radius_meters},{latitude},{longitude});',
                        f'way["amenity"="fuel"]["fuel:lpg"="yes"](around:{radius_meters},{latitude},{longitude});',
                    ]
                )

        query = f"""
        [out:json][timeout:25];
        (
          {chr(10).join(query_parts)}
        );
        out body;
        >;
        out skel qt;
        """

        return query

    def normalize_result(self, raw_result: dict) -> dict[str, Any] | None:
        """Normalize OSM result to common format."""
        tags = raw_result.get("tags", {})

        # Skip if no name
        name = tags.get("name")
        if not name:
            return None

        # Get coordinates (node has lat/lon directly, way needs center calculation)
        lat = raw_result.get("lat")
        lon = raw_result.get("lon")
        if not lat or not lon:
            # For ways, OSM returns separate lat/lon in additional elements
            # For simplicity, skip ways without direct coordinates
            return None

        # Determine POI category from OSM tags
        poi_category = self._determine_category(tags)

        # Build metadata based on category
        metadata = None
        if poi_category == POICategory.EV_CHARGING.value:
            metadata = self._extract_ev_metadata(tags)

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
            "external_id": f"osm-{raw_result['type']}-{raw_result['id']}",
            "rating": None,  # OSM doesn't provide ratings
            "distance_meters": None,  # Set by search() method
            "website": tags.get("website") or tags.get("contact:website"),
            "poi_category": poi_category,
            "metadata": metadata,
        }

    def _determine_category(self, tags: dict) -> str:
        """Determine POI category from OSM tags."""
        # Check for EV charging
        if tags.get("amenity") == "charging_station":
            return POICategory.EV_CHARGING.value

        # Check for propane
        if (tags.get("shop") == "gas" and tags.get("gas") == "lpg") or (
            tags.get("amenity") == "fuel" and tags.get("fuel:lpg") == "yes"
        ):
            return POICategory.PROPANE.value

        # Check for gas station
        if tags.get("amenity") == "fuel":
            return POICategory.GAS_STATION.value

        # Check for RV repair
        if tags.get("shop") == "caravan" or (
            tags.get("amenity") == "vehicle_inspection" and tags.get("vehicle:type") == "rv"
        ):
            return POICategory.RV_SHOP.value

        # Default to auto shop
        return POICategory.AUTO_SHOP.value

    def _extract_ev_metadata(self, tags: dict) -> dict:
        """Extract EV charging metadata from OSM tags."""
        # Parse socket types
        connector_types = []
        if tags.get("socket:type2"):
            connector_types.append("Type 2")
        if tags.get("socket:ccs"):
            connector_types.append("CCS")
        if tags.get("socket:chademo"):
            connector_types.append("CHAdeMO")
        if tags.get("socket:tesla_supercharger"):
            connector_types.append("Tesla Supercharger")
        if tags.get("socket:type1"):
            connector_types.append("Type 1 (J1772)")

        # Parse charging speeds
        charging_speeds = []
        capacity = tags.get("capacity")  # kW
        if capacity:
            try:
                kw = float(capacity)
                if kw >= 50:
                    charging_speeds.append("DC Fast")
                elif kw >= 7:
                    charging_speeds.append("Level 2")
                else:
                    charging_speeds.append("Level 1")
            except ValueError:
                # Ignore invalid capacity values - they're optional
                charging_speeds.append("Unknown")

        return {
            "connector_types": connector_types,
            "charging_speeds": charging_speeds,
            "network": tags.get("network") or tags.get("operator"),
            "availability": None,  # OSM doesn't provide real-time availability
        }

    def _calculate_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two coordinates using Haversine formula.

        Args:
            lat1: Latitude of first point
            lon1: Longitude of first point
            lat2: Latitude of second point
            lon2: Longitude of second point

        Returns:
            Distance in meters
        """
        # Earth radius in meters
        R = 6371000

        # Convert to radians
        φ1 = math.radians(lat1)
        φ2 = math.radians(lat2)
        Δφ = math.radians(lat2 - lat1)
        Δλ = math.radians(lon2 - lon1)

        # Haversine formula
        a = math.sin(Δφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(Δλ / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c

    @property
    def provider_name(self) -> str:
        """Provider name."""
        return "osm"

    @property
    def requires_api_key(self) -> bool:
        """OSM is free and doesn't require an API key."""
        return False

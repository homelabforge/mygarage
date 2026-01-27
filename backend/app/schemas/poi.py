"""Schemas for POI (Points of Interest) discovery feature."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class POISearchRequest(BaseModel):
    """Request to search for nearby Points of Interest."""

    latitude: float = Field(..., ge=-90, le=90, description="Latitude coordinate")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude coordinate")
    radius_meters: int | None = Field(
        default=8000,
        ge=100,
        le=161000,
        description="Search radius in meters (default: ~5 miles, max: ~100 miles)",
    )
    categories: list[
        Literal["auto_shop", "rv_shop", "ev_charging", "gas_station", "propane"]
    ] = Field(
        default=["auto_shop"],
        description="POI categories to search for (can select multiple)",
    )


class EVChargingMetadata(BaseModel):
    """EV charging station specific metadata."""

    connector_types: list[str] | None = Field(
        default=None,
        description="Available connector types (Type 2, CCS, CHAdeMO, etc.)",
    )
    charging_speeds: list[str] | None = Field(
        default=None, description="Charging speeds (Level 1, Level 2, DC Fast)"
    )
    network: str | None = Field(
        default=None, description="Charging network (ChargePoint, Tesla, etc.)"
    )
    availability: str | None = Field(
        default=None, description="Real-time availability status"
    )


class POIResult(BaseModel):
    """Normalized POI result from any provider (TomTom, OSM, Google, etc.)."""

    business_name: str
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    phone: str | None = None
    latitude: Decimal
    longitude: Decimal
    source: str = Field(
        description="Provider that returned this result (tomtom, osm, google, etc.)"
    )
    external_id: str | None = None
    rating: Decimal | None = None
    distance_meters: float | None = None
    website: str | None = None
    poi_category: str = Field(
        description="POI category (auto_shop, rv_shop, ev_charging, gas_station, propane)"
    )
    metadata: EVChargingMetadata | None = Field(
        default=None, description="Category-specific metadata"
    )


class POISearchResponse(BaseModel):
    """Response containing POI search results."""

    results: list[POIResult]
    count: int
    source: str = Field(
        description="Which provider was used (tomtom, osm, google, etc.)"
    )
    latitude: float
    longitude: float
    radius_meters: int


class POIRecommendation(BaseModel):
    """Recommended POI from address book based on usage."""

    id: int
    business_name: str
    address: str | None = None
    city: str | None = None
    state: str | None = None
    phone: str | None = None
    usage_count: int
    rating: Decimal | None = None
    user_rating: int | None = None
    poi_category: str | None = Field(
        default=None,
        description="POI category (auto_shop, rv_shop, ev_charging, gas_station, propane)",
    )


class POIRecommendationsResponse(BaseModel):
    """Response with recommended POIs."""

    recommendations: list[POIRecommendation]
    count: int


# Backward compatibility: Keep old schemas as aliases
# TODO: Remove in version 2.0.0
ShopSearchRequest = POISearchRequest
PlaceResult = POIResult
ShopSearchResponse = POISearchResponse
ShopRecommendation = POIRecommendation
ShopRecommendationsResponse = POIRecommendationsResponse
